from flextri.cli import main


def test_full_flow(tmp_path, example_path, capsys):
    data = tmp_path / "d.json"
    main(["--data", str(data), "onboard", "--template", str(example_path), "--name", "omer",
          "--start", "2026-10-05", "--race", "2026-12-27", "--days", "tue,wed,thu,sat,sun"])
    assert "fitted to 12 weeks" in capsys.readouterr().out
    main(["--data", str(data), "today", "--date", "2026-10-07"])
    out = capsys.readouterr().out
    assert "tempo ride" in out
    tempo_id = out.split()[0].lstrip("#")
    main(["--data", str(data), "checkin", "--date", "2026-10-07", "--workout", tempo_id, "--missed"])
    assert "Moved missed key session" in capsys.readouterr().out
    main(["--data", str(data), "finish"])
    assert "Race day, omer" in capsys.readouterr().out
