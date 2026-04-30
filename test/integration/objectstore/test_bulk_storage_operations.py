"""Integration tests for bulk storage operations (preview / execute / run status).

These run against a real Galaxy instance with a distributed object store that has
four backends:

* ``default``         – main store, weight=1, device ``tmp_disk``
* ``other``           – secondary store, weight=0, same device ``tmp_disk``
* ``separate_device`` – weight=0, different device ``other_disk``
* ``private_store``   – private disk store used for warning and quota coverage

Tests cover:
- Preview: eligibility classification and snapshot creation
- Reason codes: already_in_target, invalid_target_object_store
- Warnings: private-source to non-private target moves
- Execute: run is created and dispatched
- Run lifecycle: pending -> running -> completed
- skip_ineligible=True skips ineligible items; =False fails them
- Per-item state/reason_code details returned in the run response
- Run-items search filtering by state, reason_code, and dataset_id
- Error cases: missing snapshot (404), snapshot for wrong history (400)
- Collection (HDCA) preview: expansion, partial ineligibility
- Collection execution: all elements moved
- dataset_not_found: dataset purged between preview and execute
"""

import string
from typing import Any

from galaxy_test.base.decorators import requires_celery
from galaxy_test.base.populators import (
    DatasetCollectionPopulator,
    DatasetPopulator,
)
from ._base import BaseObjectStoreIntegrationTestCase

DISTRIBUTED_OBJECT_STORE_CONFIG_TEMPLATE = string.Template(
    """<?xml version="1.0"?>
<object_store type="distributed" id="primary" order="0">
    <backends>
        <backend id="default" allow_selection="true" type="disk" weight="1" device="tmp_disk">
            <files_dir path="${temp_directory}/files_default"/>
            <extra_dir type="temp" path="${temp_directory}/tmp_default"/>
            <extra_dir type="job_work" path="${temp_directory}/job_working_directory_default"/>
        </backend>
        <backend id="other" allow_selection="true" type="disk" weight="0" device="tmp_disk">
            <quota source="other_quota" />
            <files_dir path="${temp_directory}/files_default"/>
            <extra_dir type="temp" path="${temp_directory}/tmp_other"/>
            <extra_dir type="job_work" path="${temp_directory}/job_working_directory_other"/>
        </backend>
        <backend id="separate_device" allow_selection="true" type="disk" weight="0" device="other_disk">
            <files_dir path="${temp_directory}/files_separate"/>
            <extra_dir type="temp" path="${temp_directory}/tmp_separate"/>
            <extra_dir type="job_work" path="${temp_directory}/job_working_directory_separate"/>
        </backend>
        <backend id="private_store" allow_selection="true" type="disk" weight="0" private="true" device="private_disk">
            <quota source="private_quota" />
            <files_dir path="${temp_directory}/files_private"/>
            <extra_dir type="temp" path="${temp_directory}/tmp_private"/>
            <extra_dir type="job_work" path="${temp_directory}/job_working_directory_private"/>
        </backend>
    </backends>
</object_store>
"""
)

DEFAULT_OBJECT_STORE_ID = "default"
OTHER_OBJECT_STORE_ID = "other"
SEPARATE_DEVICE_OBJECT_STORE_ID = "separate_device"
PRIVATE_OBJECT_STORE_ID = "private_store"
FAILED_OR_SKIPPED_SEARCH = "state:failed state:skipped"
PRIVACY_DOWNGRADE_WARNING = (
    "Some selected datasets would move from private storage to shareable storage. "
    "After the operation, you will be able to share these datasets with other users."
)


class TestBulkStorageOperationsIntegration(BaseObjectStoreIntegrationTestCase):
    dataset_populator: DatasetPopulator
    dataset_collection_populator: DatasetCollectionPopulator

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        config["new_user_dataset_access_role_default_private"] = True
        cls._configure_object_store(DISTRIBUTED_OBJECT_STORE_CONFIG_TEMPLATE, config)

    def setUp(self):
        super().setUp()
        self.dataset_collection_populator = DatasetCollectionPopulator(self.galaxy_interactor)

    # ------------------------------------------------------------------ helpers

    def _preview_move(
        self,
        history_id: str,
        target_object_store_id: str,
        items: list[dict[str, Any]],
        expected_status: int = 200,
    ) -> dict[str, Any]:
        return self.dataset_populator.storage_preview(
            history_id,
            {
                "mode": "move",
                "target_object_store_id": target_object_store_id,
                "items": items,
            },
            expected_status=expected_status,
        )

    def _execute_snapshot(
        self,
        history_id: str,
        snapshot_id: str,
        skip_ineligible: bool = True,
        expected_status: int = 200,
    ) -> dict[str, Any]:
        return self.dataset_populator.storage_execute(
            history_id,
            {
                "snapshot_id": snapshot_id,
                "execution_policy": {"skip_ineligible": skip_ineligible},
            },
            expected_status=expected_status,
        )

    def _run_move(
        self,
        history_id: str,
        target_object_store_id: str,
        items: list[dict[str, Any]],
        skip_ineligible: bool = True,
        include_items_on_terminal: bool = False,
        search: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        preview = self._preview_move(history_id, target_object_store_id, items)
        execute_result = self._execute_snapshot(
            history_id,
            preview["snapshot_id"],
            skip_ineligible=skip_ineligible,
        )
        run = execute_result["run"]
        final = self.dataset_populator.wait_for_storage_run(
            history_id,
            run["run_id"],
            include_items_on_terminal=include_items_on_terminal,
            search=search,
        )
        return preview, run, final

    def _run_items(self, history_id: str, run_id: str, search: str | None = None) -> list[dict[str, Any]]:
        return self.dataset_populator.storage_run_items(history_id, run_id, search=search)

    def _item(self, hda_id: str) -> dict[str, Any]:
        return {"id": hda_id, "history_content_type": "dataset"}

    def _collection_item(self, hdca_id: str) -> dict[str, Any]:
        return {"id": hdca_id, "history_content_type": "dataset_collection"}

    def _new_list_collection(self, history_id: str, contents: list[str]) -> dict[str, Any]:
        fetch_response = self.dataset_collection_populator.create_list_in_history(
            history_id,
            contents=contents,
            wait=True,
        ).json()
        return self.dataset_collection_populator.wait_for_fetched_collection(fetch_response)

    def _assert_eligibility(
        self,
        preview: dict[str, Any],
        *,
        eligible: int,
        ineligible: int,
    ) -> dict[str, Any]:
        """Assert eligibility counts and return the eligibility dict for further checks."""
        eligibility = preview["eligibility"]
        assert eligibility["eligible_count"] == eligible
        assert eligibility["ineligible_count"] == ineligible
        return eligibility

    def _assert_run_counts(
        self,
        run: dict[str, Any],
        *,
        succeeded: int,
        failed: int,
        skipped: int,
        state: str = "completed",
        mode: str = "move",
    ) -> None:
        assert run["state"] == state
        assert run["mode"] == mode
        assert run["succeeded_count"] == succeeded
        assert run["failed_count"] == failed
        assert run["skipped_count"] == skipped
        assert run["total_count"] == succeeded + failed + skipped

    def _assert_dataset_store_and_content(
        self,
        history_id: str,
        dataset_id: str,
        object_store_id: str,
        expected_content: str,
    ) -> None:
        dataset_details = self.dataset_populator.get_history_dataset_details(history_id, dataset_id=dataset_id)
        assert dataset_details["object_store_id"] == object_store_id
        assert self.dataset_populator.get_history_dataset_content(history_id, dataset_id=dataset_id) == expected_content

    def _new_dataset_in_store(self, history_id: str, content: str, object_store_id: str) -> dict[str, Any]:
        self.dataset_populator.update_history(history_id, {"preferred_object_store_id": object_store_id})
        dataset = self.dataset_populator.new_dataset(history_id, content=content, wait=True)
        dataset_details = self.dataset_populator.get_history_dataset_details(history_id, dataset_id=dataset["id"])
        assert dataset_details["object_store_id"] == object_store_id
        return dataset

    def _unknown_encoded_id(self) -> str:
        return self._app.security.encode_id(999999999)

    # ------------------------------------------------------------------ preview tests

    def test_preview_eligible_dataset(self):
        """Preview classifies a dataset for a valid same-device move as eligible."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="test", wait=True)

            preview = self._preview_move(history_id, OTHER_OBJECT_STORE_ID, [self._item(hda["id"])])

            assert "snapshot_id" in preview
            assert "expires_at" in preview
            eligibility = self._assert_eligibility(preview, eligible=1, ineligible=0)
            assert eligibility["items"][0]["state"] == "eligible"
            assert preview["selection_counts"]["selected_items_count"] == 1
            assert preview["selection_counts"]["expanded_leaf_count"] == 1
            assert preview["selection_counts"]["unique_dataset_count"] == 1

    def test_preview_ineligible_already_in_target(self):
        """A dataset already in the target store is ineligible with reason already_in_target."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="test", wait=True)

            preview = self._preview_move(history_id, DEFAULT_OBJECT_STORE_ID, [self._item(hda["id"])])

            eligibility = self._assert_eligibility(preview, eligible=0, ineligible=1)
            item = eligibility["items"][0]
            assert item["state"] == "ineligible"
            assert item["reason_code"] == "already_in_target"

    def test_preview_move_allows_cross_device(self):
        """Move mode should allow cross-device targets (copy-then-cutover strategy)."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="test", wait=True)

            preview = self._preview_move(history_id, SEPARATE_DEVICE_OBJECT_STORE_ID, [self._item(hda["id"])])

            self._assert_eligibility(preview, eligible=1, ineligible=0)
            assert preview["estimates"]["bytes_to_transfer"] > 0
            assert isinstance(preview["estimates"]["quota_delta_transfers"], list)
            assert preview["warnings"] == []

    def test_preview_reports_quota_delta_transfers_with_source_and_target_store_ids(self):
        with self.dataset_populator.test_history() as history_id:
            hda = self._new_dataset_in_store(history_id, "quota-transfer", PRIVATE_OBJECT_STORE_ID)

            preview = self._preview_move(history_id, OTHER_OBJECT_STORE_ID, [self._item(hda["id"])])

            transfers = preview["estimates"]["quota_delta_transfers"]
            assert isinstance(transfers, list)
            assert any(
                transfer["source_object_store_id"] == PRIVATE_OBJECT_STORE_ID
                and transfer["target_object_store_id"] == OTHER_OBJECT_STORE_ID
                and transfer["bytes"] > 0
                for transfer in transfers
            )

    def test_preview_warns_on_private_to_shareable_move(self):
        with self.dataset_populator.test_history() as history_id:
            hda = self._new_dataset_in_store(history_id, "privacy-warning", PRIVATE_OBJECT_STORE_ID)

            preview = self._preview_move(history_id, OTHER_OBJECT_STORE_ID, [self._item(hda["id"])])

            self._assert_eligibility(preview, eligible=1, ineligible=0)
            assert PRIVACY_DOWNGRADE_WARNING in preview["warnings"]

    def test_preview_ineligible_invalid_target(self):
        """A non-existent target store returns invalid_target_object_store."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="test", wait=True)

            preview = self._preview_move(history_id, "does_not_exist", [self._item(hda["id"])])

            eligibility = self._assert_eligibility(preview, eligible=0, ineligible=1)
            assert eligibility["items"][0]["reason_code"] == "invalid_target_object_store"

    def test_preview_mixed_eligibility(self):
        """Preview handles a mix of eligible and ineligible items in one request."""
        with self.dataset_populator.test_history() as history_id:
            eligible_hda = self.dataset_populator.new_dataset(history_id, content="a", wait=True)
            ineligible_hda = self.dataset_populator.new_dataset(history_id, content="b", wait=True)

            self._preview_move(
                history_id,
                OTHER_OBJECT_STORE_ID,
                [
                    self._item(eligible_hda["id"]),
                    self._item(ineligible_hda["id"]),
                ],
            )

            self.dataset_populator.update_object_store_id(ineligible_hda["id"], OTHER_OBJECT_STORE_ID)

            preview = self._preview_move(
                history_id,
                OTHER_OBJECT_STORE_ID,
                [
                    self._item(eligible_hda["id"]),
                    self._item(ineligible_hda["id"]),
                ],
            )

            self._assert_eligibility(preview, eligible=1, ineligible=1)

    # ------------------------------------------------------------------ execute / run lifecycle

    def test_execute_missing_snapshot_returns_404(self):
        """Execute with an unknown snapshot_id returns HTTP 404."""
        with self.dataset_populator.test_history() as history_id:
            self._execute_snapshot(history_id, self._unknown_encoded_id(), expected_status=404)

    def test_execute_snapshot_wrong_history_returns_400(self):
        """Execute with a snapshot belonging to a different history returns HTTP 400."""
        with self.dataset_populator.test_history() as h1_id:
            with self.dataset_populator.test_history() as h2_id:
                hda = self.dataset_populator.new_dataset(h1_id, content="test", wait=True)

                preview = self._preview_move(h1_id, OTHER_OBJECT_STORE_ID, [self._item(hda["id"])])

                self._execute_snapshot(h2_id, preview["snapshot_id"], expected_status=400)

    @requires_celery
    def test_run_lifecycle_pending_to_completed(self):
        """Full lifecycle: preview -> execute -> poll until completed with succeeded_count=1."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="data", wait=True)

            _, run, final = self._run_move(history_id, OTHER_OBJECT_STORE_ID, [self._item(hda["id"])])

            assert run["state"] in ("pending", "running", "completed")
            self._assert_run_counts(final["run"], succeeded=1, failed=0, skipped=0)
            self._assert_dataset_store_and_content(history_id, hda["id"], OTHER_OBJECT_STORE_ID, "data\n")

    @requires_celery
    def test_run_per_item_status_returned(self):
        """Run response includes per-item entries with state and reason_code."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="data", wait=True)

            _, _, final = self._run_move(
                history_id,
                OTHER_OBJECT_STORE_ID,
                [self._item(hda["id"])],
                include_items_on_terminal=True,
            )

            assert len(final["items"]) == 1
            item = final["items"][0]
            assert item["state"] == "succeeded"
            assert item["reason_code"] is None

    @requires_celery
    def test_move_mode_cross_device_completes_and_updates_source_store(self):
        """Move mode to a different device uses copy-then-cutover and updates dataset source store id."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="move-cross-device", wait=True)
            before = self.dataset_populator.get_history_dataset_details(history_id, dataset_id=hda["id"])
            assert before["object_store_id"] == DEFAULT_OBJECT_STORE_ID

            _, _, final = self._run_move(
                history_id,
                SEPARATE_DEVICE_OBJECT_STORE_ID,
                [self._item(hda["id"])],
                include_items_on_terminal=True,
            )

            self._assert_run_counts(final["run"], succeeded=1, failed=0, skipped=0)
            assert final["items"][0]["state"] == "succeeded"
            assert final["items"][0]["bytes_processed"] > 0
            self._assert_dataset_store_and_content(
                history_id,
                hda["id"],
                SEPARATE_DEVICE_OBJECT_STORE_ID,
                "move-cross-device\n",
            )

    @requires_celery
    def test_successive_moves_keep_dataset_readable(self):
        """A dataset remains readable after moving across multiple stores in sequence."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="multi-hop", wait=True)

            _, _, first_final = self._run_move(history_id, OTHER_OBJECT_STORE_ID, [self._item(hda["id"])])
            self._assert_run_counts(first_final["run"], succeeded=1, failed=0, skipped=0)
            self._assert_dataset_store_and_content(history_id, hda["id"], OTHER_OBJECT_STORE_ID, "multi-hop\n")

            _, _, second_final = self._run_move(
                history_id,
                SEPARATE_DEVICE_OBJECT_STORE_ID,
                [self._item(hda["id"])],
            )
            self._assert_run_counts(second_final["run"], succeeded=1, failed=0, skipped=0)
            self._assert_dataset_store_and_content(
                history_id,
                hda["id"],
                SEPARATE_DEVICE_OBJECT_STORE_ID,
                "multi-hop\n",
            )

    @requires_celery
    def test_skip_ineligible_true_skips_not_fails(self):
        """With skip_ineligible=True an ineligible dataset is skipped, not failed."""
        with self.dataset_populator.test_history() as history_id:
            eligible = self.dataset_populator.new_dataset(history_id, content="eligible", wait=True)
            to_skip = self.dataset_populator.new_dataset(history_id, content="skip_me", wait=True)

            self.dataset_populator.update_object_store_id(to_skip["id"], OTHER_OBJECT_STORE_ID)

            _, run, final = self._run_move(
                history_id,
                OTHER_OBJECT_STORE_ID,
                [self._item(eligible["id"]), self._item(to_skip["id"])],
                include_items_on_terminal=True,
                search=FAILED_OR_SKIPPED_SEARCH,
            )

            assert run["state"] in ("pending", "running", "completed")
            self._assert_run_counts(final["run"], succeeded=1, failed=0, skipped=1)
            assert len(final["items"]) == 1
            assert final["items"][0]["dataset_id"] == to_skip["id"]
            assert final["items"][0]["state"] == "skipped"
            assert final["items"][0]["reason_code"] == "already_in_target"

            filtered_items = self._run_items(
                history_id,
                run["run_id"],
                search=f"state:skipped dataset_id:{to_skip['id']} reason_code:already_in_target",
            )
            assert len(filtered_items) == 1
            assert filtered_items[0]["dataset_id"] == to_skip["id"]
            assert filtered_items[0]["state"] == "skipped"
            assert filtered_items[0]["reason_code"] == "already_in_target"

    @requires_celery
    def test_run_items_search_filters_by_reason_code(self):
        with self.dataset_populator.test_history() as history_id:
            eligible = self.dataset_populator.new_dataset(history_id, content="eligible", wait=True)
            ineligible = self.dataset_populator.new_dataset(history_id, content="ineligible", wait=True)
            self.dataset_populator.update_object_store_id(ineligible["id"], OTHER_OBJECT_STORE_ID)

            _, run, final = self._run_move(
                history_id,
                OTHER_OBJECT_STORE_ID,
                [self._item(eligible["id"]), self._item(ineligible["id"])],
                include_items_on_terminal=True,
                search=FAILED_OR_SKIPPED_SEARCH,
            )

            self._assert_run_counts(final["run"], succeeded=1, failed=0, skipped=1)
            reason_filtered_items = self._run_items(
                history_id,
                run["run_id"],
                search="reason_code:already_in_target",
            )
            assert len(reason_filtered_items) == 1
            assert reason_filtered_items[0]["dataset_id"] == ineligible["id"]
            assert reason_filtered_items[0]["state"] == "skipped"
            assert reason_filtered_items[0]["reason_code"] == "already_in_target"

    @requires_celery
    def test_skip_ineligible_false_fails_ineligible_item(self):
        """With skip_ineligible=False an ineligible dataset produces a failed run item."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="data", wait=True)

            self.dataset_populator.update_object_store_id(hda["id"], OTHER_OBJECT_STORE_ID)

            _, _, final = self._run_move(
                history_id,
                OTHER_OBJECT_STORE_ID,
                [self._item(hda["id"])],
                skip_ineligible=False,
                include_items_on_terminal=True,
                search=FAILED_OR_SKIPPED_SEARCH,
            )

            self._assert_run_counts(final["run"], succeeded=0, failed=1, skipped=0)
            assert len(final["items"]) == 1
            assert final["items"][0]["state"] == "failed"
            assert final["items"][0]["reason_code"] == "already_in_target"

    def test_get_run_unknown_id_returns_404(self):
        """GET on an unknown run_id returns HTTP 404."""
        with self.dataset_populator.test_history() as history_id:
            self.dataset_populator.storage_run_status(history_id, self._unknown_encoded_id(), expected_status=404)

    # ------------------------------------------------------------------ collection (HDCA) tests

    def test_preview_collection_eligible(self):
        """Preview of a list collection expands elements and classifies them as eligible."""
        with self.dataset_populator.test_history() as history_id:
            hdca = self._new_list_collection(history_id, ["element1", "element2"])

            preview = self._preview_move(history_id, OTHER_OBJECT_STORE_ID, [self._collection_item(hdca["id"])])

            # Two elements means two leaf datasets, all eligible.
            eligibility = self._assert_eligibility(preview, eligible=2, ineligible=0)
            assert all(item["state"] == "eligible" for item in eligibility["items"])
            assert preview["selection_counts"]["selected_items_count"] == 1
            assert preview["selection_counts"]["expanded_leaf_count"] == 2
            assert preview["selection_counts"]["unique_dataset_count"] == 2

    def test_preview_collection_partially_ineligible(self):
        """Preview of a collection where one element is already in the target is partially ineligible."""
        with self.dataset_populator.test_history() as history_id:
            hdca = self._new_list_collection(history_id, ["elem-a", "elem-b"])

            # Move the first element to the target store so it becomes ineligible.
            first_hda_id = hdca["elements"][0]["object"]["id"]
            self.dataset_populator.update_object_store_id(first_hda_id, OTHER_OBJECT_STORE_ID)

            preview = self._preview_move(history_id, OTHER_OBJECT_STORE_ID, [self._collection_item(hdca["id"])])

            eligibility = self._assert_eligibility(preview, eligible=1, ineligible=1)
            ineligible_item = next(i for i in eligibility["items"] if i["state"] == "ineligible")
            assert ineligible_item["reason_code"] == "already_in_target"

    @requires_celery
    def test_run_collection_move_completes(self):
        """Executing a move for a list collection succeeds for all elements."""
        with self.dataset_populator.test_history() as history_id:
            hdca = self._new_list_collection(history_id, ["col-data-1", "col-data-2"])

            _, _, final = self._run_move(
                history_id,
                OTHER_OBJECT_STORE_ID,
                [self._collection_item(hdca["id"])],
                include_items_on_terminal=True,
            )

            self._assert_run_counts(final["run"], succeeded=2, failed=0, skipped=0)
            assert all(item["state"] == "succeeded" for item in final["items"])

            # Verify all element datasets moved to the target store.
            for element in hdca["elements"]:
                hda_id = element["object"]["id"]
                dataset_details = self.dataset_populator.get_history_dataset_details(history_id, dataset_id=hda_id)
                assert dataset_details["object_store_id"] == OTHER_OBJECT_STORE_ID

    # ------------------------------------------------------------------ dataset_not_found failure path

    @requires_celery
    def test_execute_dataset_purged_between_preview_and_execute(self):
        """A dataset purged after snapshot creation produces a failed run item with dataset_not_found."""
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="ephemeral", wait=True)

            preview = self._preview_move(history_id, OTHER_OBJECT_STORE_ID, [self._item(hda["id"])])

            # Purge the dataset so it no longer exists at execution time.
            self.dataset_populator.delete_dataset(history_id, hda["id"], purge=True, wait_for_purge=True)

            execute_result = self._execute_snapshot(
                history_id,
                preview["snapshot_id"],
                skip_ineligible=False,
            )
            run = execute_result["run"]
            final = self.dataset_populator.wait_for_storage_run(
                history_id,
                run["run_id"],
                include_items_on_terminal=True,
                search=FAILED_OR_SKIPPED_SEARCH,
            )

            self._assert_run_counts(final["run"], succeeded=0, failed=1, skipped=0)
            assert len(final["items"]) == 1
            assert final["items"][0]["state"] == "failed"
            assert final["items"][0]["reason_code"] == "dataset_not_found"
