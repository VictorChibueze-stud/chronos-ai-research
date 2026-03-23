import scripts.run_ui as run_ui


def test_run_ui_invokes_streamlit(monkeypatch):
    captured = {}

    def fake_run(command, check):
        captured["command"] = command
        captured["check"] = check

    monkeypatch.setattr(run_ui.subprocess, "run", fake_run)

    exit_code = run_ui.main()

    assert exit_code == 0
    assert captured["command"][1:4] == ["-m", "streamlit", "run"]
    assert captured["command"][4].endswith("src\\ui\\dashboard.py")
    assert captured["check"] is True