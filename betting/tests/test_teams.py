"""Club identity. Getting this wrong silently corrupts everything downstream."""

from vb.repo import (resolve_team, suffix_conflict, team_name, token_similarity,
                     upsert_match)


def seed(conn, names, league="E0"):
    return {name: resolve_team(conn, name, league) for name in names}


def test_abbreviations_resolve_to_the_full_club(conn):
    seed(conn, ["Manchester United"])
    for spelling in ("Man United", "Man Utd", "Manchester Utd", "Man United FC"):
        assert team_name(conn, resolve_team(conn, spelling, "E0")) == "Manchester United"


def test_two_clubs_from_the_same_city_stay_apart(conn):
    """The regression that matters: United and City are not the same club."""
    ids = seed(conn, ["Manchester United", "Manchester City"])
    assert ids["Manchester United"] != ids["Manchester City"]
    assert resolve_team(conn, "Man Utd", "E0") == ids["Manchester United"]
    assert resolve_team(conn, "Man City", "E0") == ids["Manchester City"]


def test_distinguishing_suffixes_block_a_merge(conn):
    ids = seed(conn, ["Bristol City", "Bristol Rovers"])
    assert ids["Bristol City"] != ids["Bristol Rovers"]
    assert suffix_conflict("Bristol City", "Bristol Rovers")
    assert token_similarity("Bristol City", "Bristol Rovers") == 0.0


def test_a_missing_suffix_still_matches(conn):
    seed(conn, ["Newcastle United"])
    assert team_name(conn, resolve_team(conn, "Newcastle", "E0")) == "Newcastle United"


def test_accents_and_noise_words_are_ignored(conn):
    seed(conn, ["Bayern Munich"], "D1")
    assert team_name(conn, resolve_team(conn, "Bayern München", "D1")) == "Bayern Munich"
    seed(conn, ["Atletico Madrid"], "SP1")
    assert team_name(conn, resolve_team(conn, "Atlético Madrid", "SP1")) == "Atletico Madrid"


def test_curated_aliases_win(conn):
    assert team_name(conn, resolve_team(conn, "Nott'm Forest", "E0")) == "Nottingham Forest"
    assert team_name(conn, resolve_team(conn, "M'gladbach", "D1")) == "Borussia Monchengladbach"


def test_the_same_match_from_two_feeds_is_one_row(conn):
    first = upsert_match(conn, "E0", "2025/26", "2026-01-04T15:00:00",
                         "Man United", "Arsenal", fthg=1, ftag=2, source="football-data")
    second = upsert_match(conn, "E0", "2025/26", "2026-01-04T15:00:00",
                          "Manchester United", "Arsenal", hc=7, ac=3, source="odds-api")
    assert first == second
    row = conn.execute("SELECT fthg, hc, status FROM matches WHERE id = ?", (first,)).fetchone()
    assert (row["fthg"], row["hc"], row["status"]) == (1, 7, "played")


# ---------------------------------------------------------------------------
def test_keys_can_live_in_a_file(tmp_path, monkeypatch):
    """A key belongs somewhere you edit once, not a terminal variable."""
    from vb.config import load_env_file

    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "\n"
        "API_FOOTBALL_KEY=abc123\n"
        "ODDS_API_KEY='quoted-value'\n"
        "MALFORMED LINE\n"
    )
    assert set(load_env_file(env)) == {"API_FOOTBALL_KEY", "ODDS_API_KEY"}

    import os
    assert os.environ["API_FOOTBALL_KEY"] == "abc123"
    assert os.environ["ODDS_API_KEY"] == "quoted-value", "quotes should be stripped"


def test_a_real_environment_variable_beats_the_file(tmp_path, monkeypatch):
    from vb.config import load_env_file

    monkeypatch.setenv("API_FOOTBALL_KEY", "from-the-shell")
    env = tmp_path / ".env"
    env.write_text("API_FOOTBALL_KEY=from-the-file\n")
    assert load_env_file(env) == []

    import os
    assert os.environ["API_FOOTBALL_KEY"] == "from-the-shell"


def test_a_missing_file_is_not_an_error(tmp_path):
    from vb.config import load_env_file

    assert load_env_file(tmp_path / "nothing-here") == []
