from freecleaner.models import OperationResult, ProgressUpdate


def test_operation_result_contract():
    result = OperationResult(True, "scan", data={"total": 10}).to_dict()
    assert result == {
        "total": 10,
        "ok": True,
        "op": "scan",
        "message": "",
        "cancelled": False,
    }


def test_progress_indeterminate_and_determinate():
    unknown = ProgressUpdate("update", "downloading", bytes_done=100)
    assert unknown.percent() is None
    assert unknown.to_payload()["determinate"] is False

    known = ProgressUpdate("scan", "processing", completed=3, total=4)
    assert known.percent() == 75
    assert known.to_payload()["determinate"] is True
