from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import (
    cast,
    Optional,
    TYPE_CHECKING,
    Union,
)
from uuid import UUID

from sqlalchemy import (
    false,
    or_,
)
from sqlalchemy.sql.elements import ColumnElement

from galaxy import exceptions
from galaxy.managers import datasets
from galaxy.model import (
    Dataset,
    DatasetStorageOperationRun,
    DatasetStorageOperationRunItem,
    DatasetStorageOperationSnapshot,
    HistoryDatasetAssociation,
    HistoryDatasetCollectionAssociation,
    User,
)
from galaxy.model.orm.now import now
from galaxy.model.scoped_session import galaxy_scoped_session
from galaxy.objectstore import BaseObjectStore
from galaxy.quota import QuotaAgent
from galaxy.schema.fields import EncodedDatabaseIdField
from galaxy.schema.storage_operations import (
    DatasetStorageOperationFailureReasonCode,
    StorageOperationEligibilityReasonSummary,
    StorageOperationEligibilitySummary,
    StorageOperationEstimateSummary,
    StorageOperationExecutionResult,
    StorageOperationMode,
    StorageOperationPreviewResponse,
    StorageOperationQuotaDeltaTransfer,
    StorageOperationRunItemState,
    StorageOperationRunItemStatus,
    StorageOperationRunState,
    StorageOperationRunSummary,
    StorageOperationSelectionCounts,
)
from galaxy.security import RBACAgent
from galaxy.util.custom_logging import get_logger
from galaxy.util.hash_util import (
    HashFunctionNameEnum,
    memory_bound_hexdigest,
)
from galaxy.util.search import parse_filters_structured

if TYPE_CHECKING:
    from galaxy.managers.hdcas import HDCAManager
    from galaxy.structured_app import MinimalManagerApp

log = get_logger(__name__)


MINIMUM_DAYS_TO_EXPIRATION = 10
TRANSFER_RETRY_ATTEMPTS = 3

StorageOperationContent = Union[HistoryDatasetAssociation, HistoryDatasetCollectionAssociation]
DatasetMoveValidationFailure = tuple[DatasetStorageOperationFailureReasonCode, str]


@dataclass(frozen=True)
class DatasetObjectStoreProxy:
    id: int
    uuid: UUID | str | None
    object_store_id: str


@dataclass(frozen=True)
class TargetQuotaProjection:
    projected_usage: int
    quota: int

    @property
    def exceeds_quota(self) -> bool:
        return self.projected_usage > self.quota


def _as_encoded_database_id(value: int) -> EncodedDatabaseIdField:
    return cast(EncodedDatabaseIdField, value)


@dataclass
class StorageOperationPreviewComputation:
    eligible_dataset_ids: list[int]
    eligibility_reasons: list[StorageOperationEligibilityReasonSummary]
    eligible_count: int
    ineligible_count: int
    bytes_to_transfer: int
    target_quota_delta: int
    quota_delta_transfers: list[StorageOperationQuotaDeltaTransfer]
    privacy_downgrade_count: int
    target_quota_projection: Optional[TargetQuotaProjection] = None


class DatasetStorageOperationManager:
    """Shared policy checks used by storage operation preview and execution paths."""

    def __init__(self, object_store: BaseObjectStore, hdca_manager: Optional["HDCAManager"] = None):
        self.object_store = object_store
        self._preview_builder = (
            DatasetStorageOperationPreviewBuilder(self, hdca_manager) if hdca_manager is not None else None
        )
        self._run_manager = DatasetStorageOperationRunManager(self)

    def validate_dataset_for_move(
        self,
        security_agent: RBACAgent,
        user: Optional[User],
        dataset: Dataset,
        target_object_store_id: str,
    ) -> Optional[DatasetMoveValidationFailure]:
        target_device_id = self._device_id_for_store(target_object_store_id)
        if target_device_id is None:
            return (
                DatasetStorageOperationFailureReasonCode.invalid_target_object_store,
                f"Target object store '{target_object_store_id}' is invalid.",
            )

        source_object_store_id = dataset.object_store_id
        if source_object_store_id is None:
            return (
                DatasetStorageOperationFailureReasonCode.missing_source_object_store,
                "Dataset does not define a source object store.",
            )
        if source_object_store_id == target_object_store_id:
            return (
                DatasetStorageOperationFailureReasonCode.already_in_target,
                "Dataset is already in the requested object store.",
            )

        if dataset.library_associations:
            return (
                DatasetStorageOperationFailureReasonCode.insufficient_permissions,
                "Library datasets are not eligible for object store changes.",
            )

        if user is None:
            return (
                DatasetStorageOperationFailureReasonCode.insufficient_permissions,
                "Dataset is not eligible for object store changes.",
            )

        can_change = security_agent.can_change_object_store_id(user, dataset)
        if not can_change:
            return (
                DatasetStorageOperationFailureReasonCode.shared_dataset,
                "Dataset is referenced by histories you do not own and cannot be moved.",
            )

        ok_to_edit_metadata = getattr(dataset, "ok_to_edit_metadata", None)
        if callable(ok_to_edit_metadata) and not ok_to_edit_metadata():
            return (
                DatasetStorageOperationFailureReasonCode.dataset_in_use,
                "Dataset is currently used by an active job.",
            )

        is_below_expiration_threshold = self.is_dataset_below_expiration_threshold(dataset, target_object_store_id)
        if is_below_expiration_threshold:
            return (
                DatasetStorageOperationFailureReasonCode.target_expiration_imminent,
                f"Dataset would expire in less than {MINIMUM_DAYS_TO_EXPIRATION} days after moving to the target storage.",
            )

        return None

    def target_quota_delta(
        self,
        dataset_size: int,
        source_quota_label: Optional[str],
        target_quota_label: Optional[str],
    ) -> int:
        if target_quota_label is None:
            return 0
        if source_quota_label == target_quota_label:
            return 0
        return dataset_size

    def target_quota_projection(
        self,
        quota_agent: QuotaAgent,
        user: Optional[User],
        target_object_store_id: str,
        target_quota_delta: int,
        *,
        additional_target_usage: int = 0,
    ) -> Optional[TargetQuotaProjection]:
        if target_quota_delta <= 0 or user is None:
            return None

        quota_source_label = self.object_store.get_quota_source_map().get_quota_source_label(target_object_store_id)
        quota = quota_agent.get_quota(user, quota_source_label=quota_source_label)
        if quota is None:
            return None

        if quota_source_label is None:
            usage = int(user.total_disk_usage or 0)
        else:
            quota_source_usage = user.quota_source_usage_for(quota_source_label)
            usage = int(quota_source_usage.disk_usage or 0) if quota_source_usage else 0

        projected_usage = usage + additional_target_usage + target_quota_delta
        return TargetQuotaProjection(projected_usage=projected_usage, quota=quota)

    def target_quota_exceeded_message(self, *, phase_label: str) -> str:
        return f"Operation would exceed the target quota {phase_label}."

    def requires_data_transfer(
        self,
        dataset: Dataset,
        target_object_store_id: str,
    ) -> bool:
        source_object_store_id = dataset.object_store_id
        if source_object_store_id is None:
            return True
        if source_object_store_id == target_object_store_id:
            return False
        if self.is_cross_device_move(dataset, target_object_store_id):
            return True

        source_proxy = DatasetObjectStoreProxy(
            id=dataset.id,
            uuid=dataset.uuid,
            object_store_id=source_object_store_id,
        )
        target_proxy = DatasetObjectStoreProxy(
            id=dataset.id,
            uuid=dataset.uuid,
            object_store_id=target_object_store_id,
        )
        try:
            source_path = self.object_store.construct_path(source_proxy)
            target_path = self.object_store.construct_path(target_proxy)
        except Exception:
            log.warning(
                "Falling back to data transfer for dataset %s when comparing object store paths %s -> %s",
                dataset.id,
                source_object_store_id,
                target_object_store_id,
                exc_info=True,
            )
            return True
        return source_path != target_path

    def is_privacy_downgrade_for_target(self, dataset: Dataset, target_object_store_id: str) -> bool:
        source_is_private = self._is_private_for_dataset(dataset)
        target_is_private = self._is_private_for_object_store_id(target_object_store_id)
        return source_is_private is True and target_is_private is False

    def is_target_store_expirable(self, target_object_store_id: str) -> bool:
        return self._target_store_expiration_days(target_object_store_id) is not None

    def is_dataset_below_expiration_threshold(self, dataset: Dataset, target_object_store_id: str) -> bool:
        remaining_lifetime = self._target_remaining_lifetime(dataset, target_object_store_id)
        if remaining_lifetime is None:
            return False
        return remaining_lifetime < timedelta(days=MINIMUM_DAYS_TO_EXPIRATION)

    def is_cross_device_move(self, dataset: Dataset, target_object_store_id: str) -> bool:
        source_object_store_id = dataset.object_store_id
        if source_object_store_id is None:
            return True
        source_device_id = self._device_id_for_store(source_object_store_id)
        target_device_id = self._device_id_for_store(target_object_store_id)
        if source_device_id is None or target_device_id is None:
            return True
        return source_device_id != target_device_id

    def _device_id_for_store(self, object_store_id: Optional[str]) -> Optional[str]:
        if object_store_id is None:
            return None
        return self.object_store.get_device_source_map().get_device_id(object_store_id)

    def _is_private_for_dataset(self, dataset: Dataset) -> Optional[bool]:
        try:
            return self.object_store.is_private(dataset)
        except Exception:
            return None

    def _is_private_for_object_store_id(self, object_store_id: str) -> Optional[bool]:
        try:
            proxy = SimpleNamespace(object_store_id=object_store_id)
            return self.object_store.is_private(proxy)
        except Exception:
            return None

    def _target_remaining_lifetime(self, dataset: Dataset, target_object_store_id: str) -> Optional[timedelta]:
        expiration_days = self._target_store_expiration_days(target_object_store_id)
        if expiration_days is None or dataset.create_time is None:
            return None

        expiration_time = dataset.create_time + timedelta(days=expiration_days)
        return expiration_time - now()

    def _target_store_expiration_days(self, target_object_store_id: str) -> Optional[int]:
        concrete_store = self.object_store.get_concrete_store_by_object_store_id(target_object_store_id)
        if concrete_store is None:
            return None

        expiration_days = concrete_store.object_expires_after_days
        if expiration_days is None:
            return None

        return int(expiration_days)

    def create_operation_snapshot(
        self,
        sa_session: galaxy_scoped_session,
        history_id: int,
        user_id: int,
        target_object_store_id: str,
        resolved_dataset_ids: list[int],
        eligible_dataset_ids: list[int],
        snapshot_ttl: timedelta,
    ) -> DatasetStorageOperationSnapshot:
        expires_at = now() + snapshot_ttl
        snapshot = DatasetStorageOperationSnapshot(
            history_id=history_id,
            user_id=user_id,
            mode=StorageOperationMode.move,
            target_object_store_id=target_object_store_id,
            resolved_dataset_ids=resolved_dataset_ids,
            eligible_dataset_ids=eligible_dataset_ids,
            expires_at=expires_at,
        )
        sa_session.add(snapshot)
        sa_session.commit()
        return snapshot

    def create_operation_run(
        self,
        sa_session: galaxy_scoped_session,
        snapshot: DatasetStorageOperationSnapshot,
        skip_ineligible: bool,
    ) -> DatasetStorageOperationRun:
        run = DatasetStorageOperationRun(
            snapshot_id=snapshot.id,
            history_id=snapshot.history_id,
            user_id=snapshot.user_id,
            mode=snapshot.mode,
            target_object_store_id=snapshot.target_object_store_id,
            state=StorageOperationRunState.pending.value,
            skip_ineligible=skip_ineligible,
        )
        run.total_count = len(snapshot.resolved_dataset_ids)
        sa_session.add(run)
        sa_session.commit()
        return run

    def build_preview_response(
        self,
        *,
        sa_session: galaxy_scoped_session,
        security_agent: RBACAgent,
        quota_agent: QuotaAgent,
        history_id: int,
        user: User,
        contents: list[StorageOperationContent],
        target_object_store_id: str,
        snapshot_ttl: timedelta,
        query_based_selection: bool,
    ) -> StorageOperationPreviewResponse:
        preview_builder = self._require_preview_builder()
        return preview_builder.build_preview_response(
            sa_session=sa_session,
            security_agent=security_agent,
            quota_agent=quota_agent,
            history_id=history_id,
            user=user,
            contents=contents,
            target_object_store_id=target_object_store_id,
            snapshot_ttl=snapshot_ttl,
            query_based_selection=query_based_selection,
        )

    def get_snapshot(self, sa_session: galaxy_scoped_session, snapshot_id: int) -> DatasetStorageOperationSnapshot:
        return self._run_manager.get_snapshot(sa_session, snapshot_id)

    def validate_snapshot_for_history(
        self,
        snapshot: DatasetStorageOperationSnapshot,
        *,
        history_id: int,
        user_id: int,
    ) -> None:
        self._run_manager.validate_snapshot_for_history(snapshot, history_id=history_id, user_id=user_id)

    def create_run_and_summary(
        self,
        *,
        sa_session: galaxy_scoped_session,
        snapshot: DatasetStorageOperationSnapshot,
        skip_ineligible: bool,
    ) -> tuple[DatasetStorageOperationRun, StorageOperationRunSummary]:
        return self._run_manager.create_run_and_summary(
            sa_session=sa_session,
            snapshot=snapshot,
            skip_ineligible=skip_ineligible,
        )

    def get_run(
        self,
        *,
        sa_session: galaxy_scoped_session,
        run_id: int,
        history_id: int,
        user_id: int,
    ) -> DatasetStorageOperationRun:
        return self._run_manager.get_run(
            sa_session=sa_session,
            run_id=run_id,
            history_id=history_id,
            user_id=user_id,
        )

    def to_run_summary(self, run: DatasetStorageOperationRun) -> StorageOperationRunSummary:
        return self._run_manager.to_run_summary(run)

    def get_run_items(
        self,
        *,
        sa_session: galaxy_scoped_session,
        run: DatasetStorageOperationRun,
        decode_id: Callable[[str], int],
        offset: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
    ) -> tuple[list[StorageOperationRunItemStatus], int]:
        return self._run_manager.get_run_items(
            sa_session=sa_session,
            run=run,
            decode_id=decode_id,
            offset=offset,
            limit=limit,
            search=search,
        )

    def create_run_executor(
        self,
        *,
        sa_session: galaxy_scoped_session,
        dataset_manager: datasets.DatasetManager,
        app: "MinimalManagerApp",
        run: DatasetStorageOperationRun,
        user: Optional[User],
    ) -> "StorageOperationRunExecutor":
        return StorageOperationRunExecutor(
            sa_session=sa_session,
            dataset_manager=dataset_manager,
            app=app,
            run=run,
            user=user,
            storage_operation_manager=self,
        )

    def _require_preview_builder(self) -> "DatasetStorageOperationPreviewBuilder":
        if self._preview_builder is None:
            raise RuntimeError("Preview operations require an HDCA manager.")
        return self._preview_builder


class DatasetStorageOperationPreviewBuilder:
    """Builds storage operation previews from resolved history contents."""

    def __init__(self, storage_operation_manager: DatasetStorageOperationManager, hdca_manager: "HDCAManager"):
        self.storage_operation_manager = storage_operation_manager
        self.hdca_manager = hdca_manager
        self.object_store = storage_operation_manager.object_store

    def build_preview_response(
        self,
        *,
        sa_session: galaxy_scoped_session,
        security_agent: RBACAgent,
        quota_agent: QuotaAgent,
        history_id: int,
        user: User,
        contents: list[StorageOperationContent],
        target_object_store_id: str,
        snapshot_ttl: timedelta,
        query_based_selection: bool,
    ) -> StorageOperationPreviewResponse:
        selected_items_count = len(contents)
        unique_datasets, expanded_leaf_count = self.resolve_unique_datasets_from_contents(contents)
        preview = self.compute_preview(
            security_agent=security_agent,
            quota_agent=quota_agent,
            user=user,
            unique_datasets=unique_datasets,
            target_object_store_id=target_object_store_id,
        )

        snapshot = self.storage_operation_manager.create_operation_snapshot(
            sa_session=sa_session,
            history_id=history_id,
            user_id=user.id,
            target_object_store_id=target_object_store_id,
            resolved_dataset_ids=list(unique_datasets.keys()),
            eligible_dataset_ids=preview.eligible_dataset_ids,
            snapshot_ttl=snapshot_ttl,
        )

        warnings: list[str] = []
        if query_based_selection:
            warnings.append("Selection was query-based. Execute uses a fixed snapshot to avoid selection drift.")
        if preview.target_quota_projection and preview.target_quota_projection.exceeds_quota:
            warnings.append(
                self.storage_operation_manager.target_quota_exceeded_message(phase_label="before execution")
            )
        if preview.privacy_downgrade_count > 0:
            warnings.append(
                "Some selected datasets would move from private storage to shareable storage. "
                "After the operation, you will be able to share these datasets with other users."
            )
        if self.storage_operation_manager.is_target_store_expirable(target_object_store_id):
            warnings.append(
                "Datasets in the target storage expire based on their original creation date, so they may expire sooner than expected after moving. "
            )

        return StorageOperationPreviewResponse(
            snapshot_id=_as_encoded_database_id(snapshot.id),
            selection_counts=StorageOperationSelectionCounts(
                selected_items_count=selected_items_count,
                expanded_leaf_count=expanded_leaf_count,
                unique_dataset_count=len(unique_datasets),
            ),
            eligibility=StorageOperationEligibilitySummary(
                eligible_count=preview.eligible_count,
                ineligible_count=preview.ineligible_count,
                reasons=preview.eligibility_reasons,
            ),
            estimates=StorageOperationEstimateSummary(
                bytes_to_transfer=preview.bytes_to_transfer,
                quota_delta_transfers=preview.quota_delta_transfers,
            ),
            warnings=warnings,
            expires_at=snapshot.expires_at,
        )

    def compute_preview(
        self,
        *,
        security_agent: RBACAgent,
        quota_agent: QuotaAgent,
        user: User,
        unique_datasets: dict[int, Dataset],
        target_object_store_id: str,
    ) -> StorageOperationPreviewComputation:
        eligible_dataset_ids: list[int] = []
        eligibility_reason_counts: dict[DatasetStorageOperationFailureReasonCode, int] = {}
        eligible_count = 0
        ineligible_count = 0
        bytes_to_transfer = 0
        target_quota_delta = 0
        quota_delta_transfer_totals: dict[tuple[str, str], int] = {}
        privacy_downgrade_count = 0
        quota_source_map = self.object_store.get_quota_source_map()

        for dataset_id, dataset in unique_datasets.items():
            reason = self.storage_operation_manager.validate_dataset_for_move(
                security_agent,
                user,
                dataset,
                target_object_store_id,
            )

            if reason is None:
                eligible_count += 1
                eligible_dataset_ids.append(dataset_id)
                dataset_size = int(dataset.get_total_size() or 0)
                if self.storage_operation_manager.requires_data_transfer(dataset, target_object_store_id):
                    bytes_to_transfer += dataset_size

                old_label = quota_source_map.get_quota_source_label(dataset.object_store_id) or "default"
                new_label = quota_source_map.get_quota_source_label(target_object_store_id) or "default"
                if old_label != new_label:
                    source_object_store_id = dataset.object_store_id
                    if source_object_store_id:
                        key = (source_object_store_id, target_object_store_id)
                        quota_delta_transfer_totals[key] = quota_delta_transfer_totals.get(key, 0) + dataset_size

                source_quota_label = quota_source_map.get_quota_source_label(dataset.object_store_id)
                target_quota_label = quota_source_map.get_quota_source_label(target_object_store_id)
                target_quota_delta += self.storage_operation_manager.target_quota_delta(
                    dataset_size,
                    source_quota_label,
                    target_quota_label,
                )
                if self.storage_operation_manager.is_privacy_downgrade_for_target(dataset, target_object_store_id):
                    privacy_downgrade_count += 1
            else:
                ineligible_count += 1
                reason_code, _ = reason
                self._increment_eligibility_reason(eligibility_reason_counts, reason_code)

        quota_delta_transfers = [
            StorageOperationQuotaDeltaTransfer(
                source_object_store_id=source_object_store_id,
                target_object_store_id=target_object_store_id,
                bytes=bytes_delta,
            )
            for (source_object_store_id, target_object_store_id), bytes_delta in sorted(
                quota_delta_transfer_totals.items()
            )
        ]
        target_quota_projection = self.storage_operation_manager.target_quota_projection(
            quota_agent,
            user,
            target_object_store_id,
            target_quota_delta,
        )
        if target_quota_projection and target_quota_projection.exceeds_quota:
            self._increment_eligibility_reason(
                eligibility_reason_counts,
                DatasetStorageOperationFailureReasonCode.target_quota_exceeded,
                count=eligible_count,
            )
            eligible_dataset_ids = []
            ineligible_count += eligible_count
            eligible_count = 0

        return StorageOperationPreviewComputation(
            eligible_dataset_ids=eligible_dataset_ids,
            eligibility_reasons=[
                StorageOperationEligibilityReasonSummary(
                    reason_code=reason_code,
                    count=count,
                )
                for reason_code, count in eligibility_reason_counts.items()
            ],
            eligible_count=eligible_count,
            ineligible_count=ineligible_count,
            bytes_to_transfer=bytes_to_transfer,
            target_quota_delta=target_quota_delta,
            quota_delta_transfers=quota_delta_transfers,
            privacy_downgrade_count=privacy_downgrade_count,
            target_quota_projection=target_quota_projection,
        )

    def _increment_eligibility_reason(
        self,
        eligibility_reason_counts: dict[DatasetStorageOperationFailureReasonCode, int],
        reason_code: DatasetStorageOperationFailureReasonCode,
        *,
        count: int = 1,
    ) -> None:
        if count <= 0:
            return
        eligibility_reason_counts[reason_code] = eligibility_reason_counts.get(reason_code, 0) + count

    def resolve_unique_datasets_from_contents(
        self, contents: list[StorageOperationContent]
    ) -> tuple[dict[int, Dataset], int]:
        unique_datasets: dict[int, Dataset] = {}
        expanded_leaf_count = 0

        for content in contents:
            if isinstance(content, HistoryDatasetAssociation):
                dataset = content.dataset
                if dataset is None:
                    continue
                expanded_leaf_count += 1
                unique_datasets[dataset.id] = dataset
            elif isinstance(content, HistoryDatasetCollectionAssociation):
                hdas = self.hdca_manager.map_datasets(content, fn=lambda item, *parents: item)
                for hda in hdas:
                    dataset = hda.dataset
                    if dataset is None:
                        continue
                    expanded_leaf_count += 1
                    unique_datasets[dataset.id] = dataset

        return unique_datasets, expanded_leaf_count


class DatasetStorageOperationRunManager:
    """Handles snapshot/run validation, summaries, and run-item queries."""

    def __init__(self, storage_operation_manager: DatasetStorageOperationManager):
        self.storage_operation_manager = storage_operation_manager

    def get_snapshot(self, sa_session: galaxy_scoped_session, snapshot_id: int) -> DatasetStorageOperationSnapshot:
        snapshot = sa_session.get(DatasetStorageOperationSnapshot, snapshot_id)
        if snapshot is None:
            raise exceptions.ObjectNotFound("Storage operation snapshot not found.")
        if snapshot.expires_at <= now():
            sa_session.delete(snapshot)
            sa_session.commit()
            raise exceptions.RequestParameterInvalidException("Storage operation snapshot has expired.")
        return snapshot

    def validate_snapshot_for_history(
        self,
        snapshot: DatasetStorageOperationSnapshot,
        *,
        history_id: int,
        user_id: int,
    ) -> None:
        if snapshot.history_id != history_id:
            raise exceptions.RequestParameterInvalidException("Snapshot does not belong to the requested history.")
        if snapshot.user_id != user_id:
            raise exceptions.RequestParameterInvalidException("Snapshot does not belong to the current user.")

    def create_run_and_summary(
        self,
        *,
        sa_session: galaxy_scoped_session,
        snapshot: DatasetStorageOperationSnapshot,
        skip_ineligible: bool,
    ) -> tuple[DatasetStorageOperationRun, StorageOperationRunSummary]:
        run = self.storage_operation_manager.create_operation_run(
            sa_session=sa_session,
            snapshot=snapshot,
            skip_ineligible=skip_ineligible,
        )
        return run, self.to_run_summary(run)

    def get_run(
        self,
        *,
        sa_session: galaxy_scoped_session,
        run_id: int,
        history_id: int,
        user_id: int,
    ) -> DatasetStorageOperationRun:
        run = sa_session.get(DatasetStorageOperationRun, run_id)
        if run is None:
            raise exceptions.ObjectNotFound("Storage operation run not found.")
        if run.history_id != history_id:
            raise exceptions.RequestParameterInvalidException("Run does not belong to the requested history.")
        if run.user_id != user_id:
            raise exceptions.RequestParameterInvalidException("Run does not belong to the current user.")
        return run

    def to_run_summary(self, run: DatasetStorageOperationRun) -> StorageOperationRunSummary:
        return StorageOperationRunSummary(
            run_id=_as_encoded_database_id(run.id),
            state=StorageOperationRunState(run.state),
            mode=StorageOperationMode(run.mode),
            target_object_store_id=run.target_object_store_id,
            create_time=run.create_time,
            update_time=run.update_time,
            total_count=run.total_count,
            succeeded_count=run.succeeded_count,
            failed_count=run.failed_count,
            skipped_count=run.skipped_count,
            total_bytes_processed=run.total_bytes_processed,
            task_id=UUID(str(run.task_id)) if run.task_id is not None else None,
        )

    def get_run_items(
        self,
        *,
        sa_session: galaxy_scoped_session,
        run: DatasetStorageOperationRun,
        decode_id: Callable[[str], int],
        offset: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
    ) -> tuple[list[StorageOperationRunItemStatus], int]:
        run_items_query = sa_session.query(DatasetStorageOperationRunItem).filter(
            DatasetStorageOperationRunItem.run_id == run.id
        )

        if search and search.strip():
            parsed_search = parse_filters_structured(
                search.strip(),
                {
                    "state": "state",
                    "reason": "reason_code",
                    "reason_code": "reason_code",
                    "dataset": "dataset_id",
                    "dataset_id": "dataset_id",
                },
            )

            for filter_name in ("state", "reason_code", "dataset_id"):
                filter_terms = [term for term in parsed_search.filter_terms if term.filter == filter_name]
                if not filter_terms:
                    continue

                if filter_name == "dataset_id":
                    dataset_ids = self._decode_storage_run_item_dataset_ids(
                        [term.text for term in filter_terms], decode_id=decode_id
                    )
                    if not dataset_ids:
                        run_items_query = run_items_query.filter(false())
                        break
                    run_items_query = run_items_query.filter(DatasetStorageOperationRunItem.dataset_id.in_(dataset_ids))
                    continue

                column = getattr(DatasetStorageOperationRunItem, filter_name)
                filter_conditions = []
                for term in filter_terms:
                    if term.quoted:
                        filter_conditions.append(column == term.text)
                    else:
                        filter_conditions.append(column.ilike(f"%{term.text}%"))
                run_items_query = run_items_query.filter(or_(*filter_conditions))

            for text_term in parsed_search.text_terms:
                text = text_term.text
                if not text:
                    continue

                if text_term.quoted:
                    free_text_conditions: list[ColumnElement[bool]] = [
                        DatasetStorageOperationRunItem.state == text,
                        DatasetStorageOperationRunItem.reason_code == text,
                    ]
                else:
                    free_text_conditions = [
                        DatasetStorageOperationRunItem.state.ilike(f"%{text}%"),
                        DatasetStorageOperationRunItem.reason_code.ilike(f"%{text}%"),
                    ]

                dataset_ids = self._decode_storage_run_item_dataset_ids([text], decode_id=decode_id)
                if dataset_ids:
                    free_text_conditions.append(DatasetStorageOperationRunItem.dataset_id.in_(dataset_ids))

                run_items_query = run_items_query.filter(or_(*free_text_conditions))

        total_matches = run_items_query.count()
        run_items = run_items_query.order_by(DatasetStorageOperationRunItem.id.asc()).offset(offset).limit(limit).all()
        items = [
            StorageOperationRunItemStatus(
                dataset_id=_as_encoded_database_id(run_item.dataset_id),
                state=StorageOperationRunItemState(run_item.state),
                reason_code=(
                    DatasetStorageOperationFailureReasonCode(run_item.reason_code) if run_item.reason_code else None
                ),
                bytes_processed=run_item.bytes_processed,
                create_time=run_item.create_time,
                update_time=run_item.update_time,
            )
            for run_item in run_items
        ]
        return items, total_matches

    def _decode_storage_run_item_dataset_ids(
        self,
        encoded_or_raw_ids: list[str],
        *,
        decode_id: Callable[[str], int],
    ) -> list[int]:
        dataset_ids: list[int] = []
        for value in encoded_or_raw_ids:
            if not value:
                continue
            if value.isdigit():
                dataset_ids.append(int(value))
                continue
            try:
                dataset_ids.append(decode_id(value))
            except Exception:
                continue
        return dataset_ids


class ChecksumVerificationError(ValueError):
    """Raised when post-copy checksum verification detects a mismatch."""


class StorageOperationRunExecutor:
    """Executes a storage operation run and returns notification outcome details to the caller."""

    def __init__(
        self,
        *,
        sa_session: galaxy_scoped_session,
        dataset_manager: datasets.DatasetManager,
        app: "MinimalManagerApp",
        run: DatasetStorageOperationRun,
        user: Optional[User],
        storage_operation_manager: DatasetStorageOperationManager,
    ):
        self.sa_session = sa_session
        self.dataset_manager = dataset_manager
        self.app = app
        self.run = run
        self.user = user
        self.trans = SimpleNamespace(user=user)
        self.storage_operation_manager = storage_operation_manager
        self.quota_source_map = app.object_store.get_quota_source_map()
        self.target_quota_source_label = self.quota_source_map.get_quota_source_label(run.target_object_store_id)
        self.additional_target_usage = 0
        self.succeeded_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.total_bytes_processed = 0

    def execute_run(self, snapshot: Optional[DatasetStorageOperationSnapshot]) -> StorageOperationExecutionResult:
        """Validate snapshot, drive state transitions, execute all datasets, and return execution outcome."""
        if snapshot is None:
            return self._fail_run("Bulk storage run failed because its preview snapshot could not be found.")

        if snapshot.expires_at <= now():
            return self._fail_run("Bulk storage run failed because its preview snapshot expired before execution.")

        self.run.state = "running"
        self.sa_session.add(self.run)
        self.sa_session.commit()

        resolved_dataset_ids = snapshot.resolved_dataset_ids
        succeeded_count, failed_count, skipped_count, total_bytes_processed = self._execute(resolved_dataset_ids)

        self.run.state = "completed"
        self.run.total_count = len(resolved_dataset_ids)
        self.run.succeeded_count = succeeded_count
        self.run.failed_count = failed_count
        self.run.skipped_count = skipped_count
        self.run.total_bytes_processed = total_bytes_processed
        self.sa_session.add(self.run)
        self.sa_session.commit()

        if failed_count > 0 or skipped_count > 0:
            message = "Bulk storage run finished with partial success. Check the run details for more information."
        else:
            message = f"Bulk {self.run.mode} run completed successfully for {succeeded_count} dataset(s)."

        return StorageOperationExecutionResult(state=StorageOperationRunState.completed, message=message)

    def _fail_run(self, message: str) -> StorageOperationExecutionResult:
        self.run.state = "failed"
        self.run.failed_count = self.run.total_count if self.run.total_count else 0
        self.sa_session.add(self.run)
        self.sa_session.commit()
        return StorageOperationExecutionResult(
            state=StorageOperationRunState.failed,
            message=message,
        )

    def _execute(self, resolved_dataset_ids: list[int]) -> tuple[int, int, int, int]:
        for dataset_id in resolved_dataset_ids:
            self._process_dataset(dataset_id)
        return self.succeeded_count, self.failed_count, self.skipped_count, self.total_bytes_processed

    def _process_dataset(self, dataset_id: int):
        dataset = self.sa_session.get(Dataset, dataset_id)
        if dataset is None or dataset.purged:
            self.failed_count += 1
            self._add_run_item(
                dataset_id=dataset_id,
                state="failed",
                reason_code=DatasetStorageOperationFailureReasonCode.dataset_not_found,
            )
            return

        source_quota_label = self.quota_source_map.get_quota_source_label(dataset.object_store_id)
        dataset_size = int(dataset.get_total_size() or 0)
        quota_delta = self.storage_operation_manager.target_quota_delta(
            dataset_size,
            source_quota_label,
            self.target_quota_source_label,
        )

        reason_code = self._validate_dataset(dataset, quota_delta)
        if reason_code is not None:
            self._record_ineligible(dataset_id, reason_code)
            return

        self._execute_dataset_transfer(dataset, dataset_id, quota_delta)

    def _validate_dataset(
        self,
        dataset: Dataset,
        quota_delta: int,
    ) -> Optional[DatasetStorageOperationFailureReasonCode]:
        reason = self.storage_operation_manager.validate_dataset_for_move(
            self.app.security_agent,
            self.user,
            dataset,
            self.run.target_object_store_id,
        )
        if reason is not None:
            reason_code, _message = reason
            return reason_code

        target_quota_projection = self.storage_operation_manager.target_quota_projection(
            self.app.quota_agent,
            self.user,
            self.run.target_object_store_id,
            quota_delta,
            additional_target_usage=self.additional_target_usage,
        )
        if target_quota_projection and target_quota_projection.exceeds_quota:
            return DatasetStorageOperationFailureReasonCode.target_quota_exceeded

        return None

    def _record_ineligible(
        self,
        dataset_id: int,
        reason_code: DatasetStorageOperationFailureReasonCode,
    ):
        state = "skipped" if self.run.skip_ineligible else "failed"
        if state == "skipped":
            self.skipped_count += 1
        else:
            self.failed_count += 1
        self._add_run_item(
            dataset_id=dataset_id,
            state=state,
            reason_code=reason_code,
        )

    def _execute_dataset_transfer(self, dataset: Dataset, dataset_id: int, quota_delta: int):
        source_proxy = self._dataset_proxy(dataset, str(dataset.object_store_id))
        target_proxy: Optional[DatasetObjectStoreProxy] = None
        extra_files_path_name = dataset.extra_files_path_name
        if not self._source_dataset_exists(source_proxy):
            self._record_transfer_failure(
                dataset_id,
                DatasetStorageOperationFailureReasonCode.dataset_not_found,
            )
            return

        requires_data_transfer = self.storage_operation_manager.requires_data_transfer(
            dataset, self.run.target_object_store_id
        )

        for attempt in range(1, TRANSFER_RETRY_ATTEMPTS + 1):
            target_proxy: Optional[DatasetObjectStoreProxy] = None
            try:
                bytes_processed = 0
                if requires_data_transfer:
                    target_proxy = self._dataset_proxy(dataset, self.run.target_object_store_id)
                    bytes_processed = self._copy_dataset_to_target_store(dataset, self.run.target_object_store_id)
                    self._verify_copied_dataset_integrity(dataset, self.run.target_object_store_id)
                    self._finalize_cross_device_move(dataset, self.run.target_object_store_id)
                    self._cleanup_source_dataset_data(source_proxy, extra_files_path_name)
                else:
                    self.dataset_manager.update_object_store_id(self.trans, dataset, self.run.target_object_store_id)

                self.additional_target_usage += quota_delta
                self.succeeded_count += 1
                self.total_bytes_processed += bytes_processed
                self._add_run_item(dataset_id=dataset_id, state="succeeded", bytes_processed=bytes_processed)
                self._notify_dataset_update(dataset)
                return
            except ChecksumVerificationError as exc:
                log.warning(
                    "Integrity verification failed for run %s dataset %s (attempt %s/%s): %s",
                    self.run.id,
                    dataset.id,
                    attempt,
                    TRANSFER_RETRY_ATTEMPTS,
                    exc,
                )
                if target_proxy is not None:
                    self._cleanup_target_dataset_data(target_proxy, extra_files_path_name)
                if attempt < TRANSFER_RETRY_ATTEMPTS and requires_data_transfer:
                    continue
                self._record_transfer_failure(
                    dataset_id,
                    DatasetStorageOperationFailureReasonCode.checksum_verification_failed,
                )
                return
            except Exception:
                log.exception(
                    "Storage operation execution error for run %s dataset %s (attempt %s/%s)",
                    self.run.id,
                    dataset.id,
                    attempt,
                    TRANSFER_RETRY_ATTEMPTS,
                )
                if target_proxy is not None:
                    self._cleanup_target_dataset_data(target_proxy, extra_files_path_name)
                if attempt < TRANSFER_RETRY_ATTEMPTS and requires_data_transfer:
                    continue
                self._record_transfer_failure(
                    dataset_id,
                    DatasetStorageOperationFailureReasonCode.execution_error,
                )
                return

    def _source_dataset_exists(self, source_proxy: DatasetObjectStoreProxy) -> bool:
        try:
            return bool(self.app.object_store.exists(source_proxy))
        except Exception:
            return False

    def _notify_dataset_update(self, dataset: Dataset):
        # Touching the dataset update time will trigger a refresh in the UI
        dataset.touch_collection_update_time()

    def _record_transfer_failure(
        self,
        dataset_id: int,
        reason_code: DatasetStorageOperationFailureReasonCode,
    ) -> None:
        self.failed_count += 1
        self._add_run_item(
            dataset_id=dataset_id,
            state="failed",
            reason_code=reason_code,
        )

    def _add_run_item(
        self,
        *,
        dataset_id: int,
        state: str,
        reason_code: Optional[DatasetStorageOperationFailureReasonCode] = None,
        bytes_processed: int = 0,
    ):
        self.sa_session.add(
            DatasetStorageOperationRunItem(
                run_id=self.run.id,
                dataset_id=dataset_id,
                state=state,
                reason_code=reason_code,
                bytes_processed=bytes_processed,
            )
        )

    def _dataset_proxy(self, dataset: Dataset, object_store_id: str) -> DatasetObjectStoreProxy:
        return DatasetObjectStoreProxy(id=dataset.id, uuid=dataset.uuid, object_store_id=object_store_id)

    def _copy_dataset_to_target_store(self, dataset: Dataset, target_object_store_id: str) -> int:
        source_proxy = self._dataset_proxy(dataset, str(dataset.object_store_id))
        target_proxy = self._dataset_proxy(dataset, target_object_store_id)

        source_filename = self.app.object_store.get_filename(source_proxy)
        self.app.object_store.update_from_file(
            target_proxy,
            file_name=source_filename,
            create=True,
            preserve_symlinks=False,
        )

        extra_files_path_name = dataset.extra_files_path_name
        if extra_files_path_name:
            self._copy_extra_files(source_proxy, target_proxy, extra_files_path_name)

        return int(dataset.get_total_size() or 0)

    def _copy_extra_files(
        self,
        source_proxy: DatasetObjectStoreProxy,
        target_proxy: DatasetObjectStoreProxy,
        extra_files_path_name: str,
    ) -> None:
        if not self.app.object_store.exists(source_proxy, dir_only=True, extra_dir=extra_files_path_name):
            return

        src_extra_dir = Path(
            self.app.object_store.get_filename(source_proxy, dir_only=True, extra_dir=extra_files_path_name)
        )
        for file_path in src_extra_dir.rglob("*"):
            if not file_path.is_file():
                continue
            relative_parent = file_path.parent.relative_to(src_extra_dir)
            extra_dir = extra_files_path_name
            if str(relative_parent) != ".":
                extra_dir = f"{extra_files_path_name}/{relative_parent.as_posix()}"
            self.app.object_store.update_from_file(
                target_proxy,
                extra_dir=extra_dir,
                alt_name=file_path.name,
                file_name=str(file_path),
                create=True,
                preserve_symlinks=False,
            )

    def _verify_copied_dataset_integrity(self, dataset: Dataset, target_object_store_id: str):
        source_proxy = self._dataset_proxy(dataset, str(dataset.object_store_id))
        target_proxy = self._dataset_proxy(dataset, target_object_store_id)

        source_filename = self.app.object_store.get_filename(source_proxy)
        target_filename = self.app.object_store.get_filename(target_proxy)
        source_hash = self._sha256(source_filename)
        target_hash = self._sha256(target_filename)
        if source_hash != target_hash:
            raise ChecksumVerificationError("Primary file checksum mismatch between source and target.")

        extra_files_path_name = dataset.extra_files_path_name
        if not extra_files_path_name:
            return

        self._verify_extra_files_integrity(
            source_proxy=source_proxy,
            target_proxy=target_proxy,
            extra_files_path_name=extra_files_path_name,
        )

    def _verify_extra_files_integrity(
        self,
        *,
        source_proxy: DatasetObjectStoreProxy,
        target_proxy: DatasetObjectStoreProxy,
        extra_files_path_name: str,
    ) -> None:

        source_has_extra = self.app.object_store.exists(source_proxy, dir_only=True, extra_dir=extra_files_path_name)
        target_has_extra = self.app.object_store.exists(target_proxy, dir_only=True, extra_dir=extra_files_path_name)
        if source_has_extra != target_has_extra:
            raise ChecksumVerificationError("Extra files presence differs between source and target.")
        if not source_has_extra:
            return

        src_extra_dir = Path(
            self.app.object_store.get_filename(source_proxy, dir_only=True, extra_dir=extra_files_path_name)
        )
        tgt_extra_dir = Path(
            self.app.object_store.get_filename(target_proxy, dir_only=True, extra_dir=extra_files_path_name)
        )

        source_rel_paths = {
            file_path.relative_to(src_extra_dir).as_posix()
            for file_path in src_extra_dir.rglob("*")
            if file_path.is_file()
        }
        target_rel_paths = {
            file_path.relative_to(tgt_extra_dir).as_posix()
            for file_path in tgt_extra_dir.rglob("*")
            if file_path.is_file()
        }
        if source_rel_paths != target_rel_paths:
            raise ChecksumVerificationError("Extra files layout differs between source and target.")

        for relative_path in sorted(source_rel_paths):
            source_file = src_extra_dir / relative_path
            target_file = tgt_extra_dir / relative_path
            source_hash = self._sha256(str(source_file))
            target_hash = self._sha256(str(target_file))
            if source_hash != target_hash:
                raise ChecksumVerificationError("Extra file checksum mismatch between source and target.")

    def _sha256(self, path: str) -> str:
        return memory_bound_hexdigest(hash_func_name=HashFunctionNameEnum.sha256, path=path)

    def _cleanup_source_dataset_data(
        self,
        source_proxy: DatasetObjectStoreProxy,
        extra_files_path_name: Optional[str],
    ) -> None:
        try:
            self.app.object_store.delete(source_proxy)
        except Exception:
            log.warning(
                "Failed to delete source dataset file after storage move for run %s dataset %s",
                self.run.id,
                source_proxy.id,
                exc_info=True,
            )

        if not extra_files_path_name:
            return

        try:
            if self.app.object_store.exists(source_proxy, dir_only=True, extra_dir=extra_files_path_name):
                self.app.object_store.delete(
                    source_proxy,
                    entire_dir=True,
                    extra_dir=extra_files_path_name,
                    dir_only=True,
                )
        except Exception:
            log.warning(
                "Failed to delete source extra files after storage move for run %s dataset %s",
                self.run.id,
                source_proxy.id,
                exc_info=True,
            )

    def _cleanup_target_dataset_data(
        self,
        target_proxy: DatasetObjectStoreProxy,
        extra_files_path_name: Optional[str],
    ) -> None:
        try:
            self.app.object_store.delete(target_proxy)
        except Exception:
            log.warning(
                "Failed to delete target dataset file while rolling back failed storage move for run %s dataset %s",
                self.run.id,
                target_proxy.id,
                exc_info=True,
            )

        if not extra_files_path_name:
            return

        try:
            if self.app.object_store.exists(target_proxy, dir_only=True, extra_dir=extra_files_path_name):
                self.app.object_store.delete(
                    target_proxy,
                    entire_dir=True,
                    extra_dir=extra_files_path_name,
                    dir_only=True,
                )
        except Exception:
            log.warning(
                "Failed to delete target extra files while rolling back failed storage move for run %s dataset %s",
                self.run.id,
                target_proxy.id,
                exc_info=True,
            )

    def _finalize_cross_device_move(self, dataset: Dataset, target_object_store_id: str):
        old_object_store_id = dataset.object_store_id
        quota_source_map = self.app.object_store.get_quota_source_map()
        if quota_source_map:
            old_label = quota_source_map.get_quota_source_label(old_object_store_id)
            new_label = quota_source_map.get_quota_source_label(target_object_store_id)
            if old_label != new_label and self.user is not None:
                self.app.quota_agent.relabel_quota_for_dataset(dataset, old_label, new_label)
        dataset.object_store_id = target_object_store_id
        self.sa_session.add(dataset)
