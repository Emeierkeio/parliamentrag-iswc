"""Nightly amendment download: Chamber file keys, targets, conditional requests; Senate HTML merge."""

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import download_emendamenti_camera as C  # noqa: E402
import parse_emendamenti as P  # noqa: E402


def _fase(numero, data=""):
    return {"idFase": "1", "idDdl": "9", "fase": f"C.{numero}", "numeroFase": numero, "stato": "", "data": data}


def test_camera_key_matches_the_act_uri():
    assert C.camera_key("0005") == "5"
    assert C.camera_key("1038-B") == "1038-B"
    assert C.camera_key("384-446-459-B") == "384-B"
    assert C.camera_key("643-BIS") == "643-bis"
    assert C.camera_key("2112-quinquies") == "2112-quinquies"
    assert C.camera_key("643-BIS/I") is None


def test_nightly_targets_ask_saved_files_and_suffixed_readings():
    today = dt.date(2026, 10, 24)
    recent = (today - dt.timedelta(days=2)).isoformat()
    fasi = [_fase("1", "2023-01-01"), _fase("2", recent), _fase("3", "2023-01-01"), _fase("3-B", "2023-08-04")]
    have = {"1", "2"}
    missing = {str(n) for n in range(4, 40)}
    targets, full, top = C.select_targets(fasi, 14, have, missing, today)
    assert top == 3 + C.PROBE_AHEAD  # highest reading or saved file, not the 404s probed ahead
    assert C.select_targets([], 14, set(), missing, today)[2] == 39 + C.PROBE_AHEAD
    assert full == {"2"}
    assert {"1", "2"} <= set(targets)  # saved files are always asked
    assert {"3", "3-B"} <= set(targets)  # never probed
    slice_ = {k for k in missing if k in targets}
    assert slice_ and all(int(k) % C.REPROBE_NIGHTS == today.toordinal() % C.REPROBE_NIGHTS for k in slice_)
    assert targets == sorted(targets, key=C.key_order)
    # over a week every 404 is asked again
    week = set()
    for d in range(C.REPROBE_NIGHTS):
        week |= set(C.select_targets(fasi, 14, have, missing, today + dt.timedelta(days=d))[0])
    assert missing <= week


def test_conditional_headers(tmp_path):
    f = tmp_path / "ac.1.xml"
    assert C.conditional_headers(f, full=False) == {}
    f.write_text("<?xml?>")
    os.utime(f, (1_700_000_000, 1_700_000_000))
    assert C.conditional_headers(f, full=False) == {"If-Modified-Since": "Tue, 14 Nov 2023 22:13:20 GMT"}
    assert C.conditional_headers(f, full=True) == {}


def test_save_fasi_keys_and_id_ddl(tmp_path, monkeypatch):
    cache = tmp_path / "emendamenti" / "fasi_camera_leg19.csv"
    C.save_fasi([dict(_fase("643-BIS"), idDdl="51916"), dict(_fase("643-BIS/I"), idDdl="52048"),
                 dict(_fase("0005"), idDdl="7")], cache)
    monkeypatch.setattr(P, "DOWNLOADS", tmp_path)
    assert P.camera_id_ddl(19) == {"5": "7", "643-bis": "51916"}


def test_camera_files_sorted_with_suffix(tmp_path):
    names = ["ac.1039.xml", "ac.1038-B.xml", "ac.643-bis.xml", "ac.1038.xml"]
    paths = sorted((tmp_path / n for n in names), key=P.camera_file_order)
    assert [p.name for p in paths] == ["ac.643-bis.xml", "ac.1038.xml", "ac.1038-B.xml", "ac.1039.xml"]


def test_senate_html_adds_only_numbers_missing_from_akn():
    akn = [{"ramo": "S", "sede": "commissione", "atto": "S.10", "atti_congiunti": ["S.11"],
            "numero": "1.1", "versione": None},
           {"ramo": "S", "sede": "assemblea", "atto": "S.10", "atti_congiunti": [],
            "numero": "1.2", "versione": None}]
    known = P.akn_committee_numbers(akn)
    html_rows = [{"numero": "1.1", "versione": None}, {"numero": "1.1", "versione": "testo 2"},
                 {"numero": "1.2", "versione": None}]
    assert P.html_rows_missing_from_akn(html_rows, known["S.10"]) == html_rows[1:]
    assert P.html_rows_missing_from_akn(html_rows, known["S.11"]) == html_rows[1:]
