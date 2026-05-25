from tide_mcp.tools import list_gates


def test_list_gates_reports_coverage():
    result = list_gates()
    dests = {c["destination"] for c in result["coverage"]}
    assert "Nanaimo" in dests
    assert "Friday Harbor" in dests
    assert isinstance(result["display"], str) and "Nanaimo" in result["display"]
