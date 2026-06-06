from currents_mcp.passages import GATES, find_gate, match_destination, coverage


def test_known_gate_has_chs_station():
    gate = GATES["Dodd Narrows"]
    assert gate.provider == "chs"
    assert gate.station_id == "63aef1866a2b9417c035030f"


def test_find_gate_is_case_insensitive():
    assert find_gate("dodd narrows").name == "Dodd Narrows"
    assert find_gate("DODD NARROWS").name == "Dodd Narrows"
    assert find_gate("nope") is None


def test_match_destination_by_alias():
    p = match_destination("prideaux haven")
    assert p.destination == "Desolation Sound"
    assert p.gate_names == ()  # open-water, no gates


def test_match_destination_with_gates_is_ordered():
    p = match_destination("Cordero Channel")
    assert p.gate_names == ("Gillard Passage", "Dent Rapids")


def test_match_destination_unknown_returns_none():
    assert match_destination("Atlantis") is None


def test_boundary_pass_is_noaa():
    assert GATES["Boundary Pass"].provider == "noaa"
    assert GATES["Boundary Pass"].noaa_bin == 35


def test_coverage_lists_destinations_and_gates():
    cov = coverage()
    names = {c["destination"] for c in cov}
    assert "Nanaimo" in names and "Friday Harbor" in names
