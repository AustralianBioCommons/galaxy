from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import (
    Any,
    Optional,
)

from galaxy.model import (
    Dataset,
    DatasetStorageOperationRun,
    DatasetStorageOperationRunItem,
    DatasetStorageOperationSnapshot,
    User,
)
from galaxy.model.orm.now import now
from galaxy.model.scoped_session import galaxy_scoped_session
from galaxy.objectstore import BaseObjectStore
from galaxy.schema.storage_operations import (
    DatasetStorageOperationFailureReasonCode,
    StorageOperationExecutionResult,
    StorageOperationMode,
    StorageOperationRunState,
)
from galaxy.util.custom_logging import get_logger
from galaxy.util.hash_util import (
    HashFunctionNameEnum,
    memory_bound_hexdigest,
)

log = get_logger(__name__)


class DatasetStorageOperationManager:
    """Shared policy checks used by storage operation preview and execution paths."""

    def __init__(self, object_store: BaseObjectStore):
        self.object_store = object_store

    def validate_dataset_for_mode(
        self,
        security_agent,
        user: Optional[User],
        dataset: Dataset,
        mode: StorageOperationMode,
        target_object_store_id: str,
    ) -> Optional[tuple[DatasetStorageOperationFailureReasonCode, str]]:
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

        can_change = bool(user) and security_agent.can_change_object_store_id(user, dataset)
        if not can_change:
            return (
                DatasetStorageOperationFailureReasonCode.insufficient_permissions,
                "Dataset is not eligible for object store changes.",
            )

        ok_to_edit_metadata = getattr(dataset, "ok_to_edit_metadata", None)
        if callable(ok_to_edit_metadata) and not ok_to_edit_metadata():
            return (
                DatasetStorageOperationFailureReasonCode.dataset_in_use,
                "Dataset is currently used by an active job.",
            )

        return None

    def target_quota_delta_for_mode(
        self,
        mode: StorageOperationMode,
        dataset_size: int,
        source_quota_label: Optional[str],
        target_quota_label: Optional[str],
    ) -> int:
        if mode == StorageOperationMode.copy:
            return dataset_size
        if target_quota_label is None:
            return 0
        if source_quota_label == target_quota_label:
            return 0
        return dataset_size

    def validate_target_quota_projection(
        self,
        quota_agent,
        user: Optional[User],
        target_object_store_id: str,
        target_quota_delta: int,
        *,
        additional_target_usage: int = 0,
        phase_label: str = "before execution",
    ) -> Optional[str]:
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
        if projected_usage > quota:
            return (
                f"Operation would exceed target quota {phase_label} "
                f"(projected {projected_usage} bytes > quota {quota} bytes)."
            )
        return None

    def requires_data_transfer(
        self,
        dataset: Dataset,
        mode: StorageOperationMode,
        target_object_store_id: str,
    ) -> bool:
        if mode == StorageOperationMode.copy:
            return True
        return self.is_cross_device_move(dataset, target_object_store_id)

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

    def create_operation_snapshot(
        self,
        sa_session: galaxy_scoped_session,
        history_id: int,
        user_id: int,
        mode: StorageOperationMode,
        target_object_store_id: str,
        resolved_dataset_ids: list[int],
        eligible_dataset_ids: list[int],
        snapshot_ttl: timedelta,
    ) -> DatasetStorageOperationSnapshot:
        expires_at = now() + snapshot_ttl
        snapshot = DatasetStorageOperationSnapshot(
            history_id=history_id,
            user_id=user_id,
            mode=mode,
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
        sa_session.add(run)
        run.total_count = len(snapshot.resolved_dataset_ids)
        sa_session.add(run)
        sa_session.commit()
        return run


class ChecksumVerificationError(ValueError):
    """Raised when post-copy checksum verification detects a mismatch."""


class StorageOperationRunExecutor:
    """Executes a storage operation run and returns notification outcome details to the caller."""

    def __init__(
        self,
        *,
        sa_session: galaxy_scoped_session,
        dataset_manager: Any,
        app: Any,
        run: DatasetStorageOperationRun,
        user: Optional[User],
        run_mode: StorageOperationMode,
    ):
        self.sa_session = sa_session
        self.dataset_manager = dataset_manager
        self.app = app
        self.run = run
        self.user = user
        self.run_mode = run_mode
        self.trans = SimpleNamespace(user=user)
        self.storage_operation_manager = DatasetStorageOperationManager(app.object_store)
        self.quota_source_map = app.object_store.get_quota_source_map()
        self.target_quota_source_label = self.quota_source_map.get_quota_source_label(run.target_object_store_id)
        self.additional_target_usage = 0
        self.succeeded_count = 0
        self.failed_count = 0
        self.skipped_count = 0

    def execute_run(self, snapshot: Optional[DatasetStorageOperationSnapshot]) -> StorageOperationExecutionResult:
        """Validate snapshot, drive state transitions, execute all datasets, and return execution outcome."""
        if snapshot is None:
            self.run.state = "failed"
            self.run.failed_count = self.run.total_count if self.run.total_count else 0
            self.sa_session.add(self.run)
            self.sa_session.commit()
            return StorageOperationExecutionResult(
                state=StorageOperationRunState.failed,
                message="Bulk storage run failed because its preview snapshot could not be found.",
            )

        if snapshot.expires_at <= now():
            self.run.state = "failed"
            self.run.failed_count = self.run.total_count if self.run.total_count else 0
            self.sa_session.add(self.run)
            self.sa_session.commit()
            return StorageOperationExecutionResult(
                state=StorageOperationRunState.failed,
                message="Bulk storage run failed because its preview snapshot expired before execution.",
            )

        self.run.state = "running"
        self.sa_session.add(self.run)
        self.sa_session.commit()

        resolved_dataset_ids = snapshot.resolved_dataset_ids
        succeeded_count, failed_count, skipped_count = self._execute(resolved_dataset_ids)

        self.run.state = "completed"
        self.run.total_count = len(resolved_dataset_ids)
        self.run.succeeded_count = succeeded_count
        self.run.failed_count = failed_count
        self.run.skipped_count = skipped_count
        self.sa_session.add(self.run)
        self.sa_session.commit()

        if failed_count > 0 or skipped_count > 0:
            message = "Bulk storage run finished with partial success. Check the run details for more information."
        else:
            message = f"Bulk {self.run.mode} run completed successfully for {succeeded_count} dataset(s)."

        return StorageOperationExecutionResult(state=StorageOperationRunState.completed, message=message)

    def _execute(self, resolved_dataset_ids: list[int]) -> tuple[int, int, int]:
        for dataset_id in resolved_dataset_ids:
            self._process_dataset(dataset_id)
        return self.succeeded_count, self.failed_count, self.skipped_count

    def _process_dataset(self, dataset_id: int):
        dataset = self.sa_session.get(Dataset, dataset_id)
        if dataset is None:
            self.failed_count += 1
            self._add_run_item(
                dataset_id=dataset_id,
                state="failed",
                reason_code=DatasetStorageOperationFailureReasonCode.dataset_not_found,
                message="Dataset was not found at execution time.",
            )
            return

        source_quota_label = self.quota_source_map.get_quota_source_label(dataset.object_store_id)
        dataset_size = int(dataset.get_total_size() or 0)
        quota_delta = self.storage_operation_manager.target_quota_delta_for_mode(
            self.run_mode,
            dataset_size,
            source_quota_label,
            self.target_quota_source_label,
        )

        reason_code, message = self._validate_dataset(dataset, quota_delta)
        if reason_code is not None:
            self._record_ineligible(dataset_id, reason_code, message)
            return

        self._execute_dataset_transfer(dataset, dataset_id, quota_delta)

    def _validate_dataset(
        self,
        dataset: Dataset,
        quota_delta: int,
    ) -> tuple[Optional[DatasetStorageOperationFailureReasonCode], Optional[str]]:
        reason = self.storage_operation_manager.validate_dataset_for_mode(
            self.app.security_agent,
            self.user,
            dataset,
            self.run_mode,
            self.run.target_object_store_id,
        )
        if reason is not None:
            return reason

        quota_message = self.storage_operation_manager.validate_target_quota_projection(
            self.app.quota_agent,
            self.user,
            self.run.target_object_store_id,
            quota_delta,
            additional_target_usage=self.additional_target_usage,
            phase_label="at execution time",
        )
        if quota_message is not None:
            return DatasetStorageOperationFailureReasonCode.target_quota_exceeded, quota_message

        return None, None

    def _record_ineligible(
        self,
        dataset_id: int,
        reason_code: DatasetStorageOperationFailureReasonCode,
        message: Optional[str],
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
            message=message,
        )

    def _execute_dataset_transfer(self, dataset: Dataset, dataset_id: int, quota_delta: int):
        try:
            bytes_processed = 0
            if self.run_mode == StorageOperationMode.move:
                if self.storage_operation_manager.is_cross_device_move(dataset, self.run.target_object_store_id):
                    bytes_processed = self._copy_dataset_to_target_store(dataset, self.run.target_object_store_id)
                    self._verify_copied_dataset_integrity(dataset, self.run.target_object_store_id)
                    self._finalize_cross_device_move(dataset, self.run.target_object_store_id)
                else:
                    self.dataset_manager.update_object_store_id(self.trans, dataset, self.run.target_object_store_id)
            else:
                bytes_processed = self._copy_dataset_to_target_store(dataset, self.run.target_object_store_id)
                self._verify_copied_dataset_integrity(dataset, self.run.target_object_store_id)

            self.additional_target_usage += quota_delta
            self.succeeded_count += 1
            self._add_run_item(dataset_id=dataset_id, state="succeeded", bytes_processed=bytes_processed)
            dataset.touch_collection_update_time()
        except ChecksumVerificationError as exc:
            self.failed_count += 1
            self._add_run_item(
                dataset_id=dataset_id,
                state="failed",
                reason_code=DatasetStorageOperationFailureReasonCode.checksum_verification_failed,
                message=str(exc),
            )
        except Exception as exc:
            self.failed_count += 1
            self._add_run_item(
                dataset_id=dataset_id,
                state="failed",
                reason_code=DatasetStorageOperationFailureReasonCode.execution_error,
                message=str(exc),
            )

    def _add_run_item(
        self,
        *,
        dataset_id: int,
        state: str,
        reason_code: Optional[DatasetStorageOperationFailureReasonCode] = None,
        message: Optional[str] = None,
        bytes_processed: int = 0,
    ):
        self.sa_session.add(
            DatasetStorageOperationRunItem(
                run_id=self.run.id,
                dataset_id=dataset_id,
                state=state,
                reason_code=reason_code,
                message=message,
                bytes_processed=bytes_processed,
            )
        )

    def _dataset_proxy(self, dataset: Dataset, object_store_id: str) -> Any:
        return SimpleNamespace(id=dataset.id, uuid=dataset.uuid, object_store_id=object_store_id)

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
        if extra_files_path_name and self.app.object_store.exists(
            source_proxy, dir_only=True, extra_dir=extra_files_path_name
        ):
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

        return int(dataset.get_total_size() or 0)

    def _verify_copied_dataset_integrity(self, dataset: Dataset, target_object_store_id: str):
        source_proxy = self._dataset_proxy(dataset, str(dataset.object_store_id))
        target_proxy = self._dataset_proxy(dataset, target_object_store_id)

        source_filename = self.app.object_store.get_filename(source_proxy)
        target_filename = self.app.object_store.get_filename(target_proxy)
        source_hash = memory_bound_hexdigest(hash_func_name=HashFunctionNameEnum.sha256, path=source_filename)
        target_hash = memory_bound_hexdigest(hash_func_name=HashFunctionNameEnum.sha256, path=target_filename)
        if source_hash != target_hash:
            raise ChecksumVerificationError(
                f"Checksum verification failed for dataset {dataset.id}: source hash {source_hash} != target hash {target_hash}."
            )

        extra_files_path_name = dataset.extra_files_path_name
        if not extra_files_path_name:
            return

        source_has_extra = self.app.object_store.exists(source_proxy, dir_only=True, extra_dir=extra_files_path_name)
        target_has_extra = self.app.object_store.exists(target_proxy, dir_only=True, extra_dir=extra_files_path_name)
        if source_has_extra != target_has_extra:
            raise ChecksumVerificationError(
                f"Checksum verification failed for dataset {dataset.id}: extra files presence differs between source and target."
            )
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
            raise ChecksumVerificationError(
                f"Checksum verification failed for dataset {dataset.id}: extra files layout differs between source and target."
            )

        for relative_path in sorted(source_rel_paths):
            source_file = src_extra_dir / relative_path
            target_file = tgt_extra_dir / relative_path
            source_hash = memory_bound_hexdigest(hash_func_name=HashFunctionNameEnum.sha256, path=str(source_file))
            target_hash = memory_bound_hexdigest(hash_func_name=HashFunctionNameEnum.sha256, path=str(target_file))
            if source_hash != target_hash:
                raise ChecksumVerificationError(
                    f"Checksum verification failed for dataset {dataset.id} extra file '{relative_path}': "
                    f"source hash {source_hash} != target hash {target_hash}."
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
