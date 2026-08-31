"""API-Football adapter, exercised against recorded shapes.

The live API is unreachable from the machine this was written on, so every test
drives the adapter with a stubbed transport. That makes these tests a
specification of what the code expects rather than proof the API agrees — which
is exactly why `vb apifootball check` exists, and why the parsing is defensive.
"""

import pytest

from vb.sources import apifootball as af


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        return self._payload


def stub(monkeypatch, payload, status=200, headers=None, capture=None):
    def fake_get(url, params=None, headers=None, timeout=None):
        if capture is not None:
            capture.append({"url": url, "params": params, "headers": headers})
        body = payload(params) if callable(payload) else payload
        return FakeResponse(body, status, {"x-ratelimit-requests-limit": "100",
                                           "x-ratelimit-requests-remaining": "97"})
    monkeypatch.setattr(af.requests, "get", fake_get)


def envelope(response, errors=None):
    return {"get": "x", "parameters": {}, "errors": errors or [],
            "results": len(response), "response": response}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "short-direct-key-123456")
    monkeypatch.setattr(af, "_read_cache", lambda *a, **k: None)
    monkeypatch.setattr(af, "_write_cache", lambda *a, **k: None)
    return af.Client(budget=af.Budget())


# --- budget ----------------------------------------------------------------
def test_budget_learns_the_allowance_from_the_reply(client, monkeypatch):
    stub(monkeypatch, envelope([{"ok": True}]))
    client.get("status")
    assert client.budget.limit == 100
    assert client.budget.remaining == 97
    assert client.budget.used_this_run == 1


def test_budget_stops_before_the_allowance_runs_out(client):
    client.budget.remaining = 5
    client.budget.reserve = 5
    with pytest.raises(af.BudgetExhausted) as exc:
        client.budget.check("the rest of the card")
    assert "the rest of the card" in str(exc.value)


def test_budget_respects_a_per_run_cap(client, monkeypatch):
    client.budget.max_this_run = 1
    stub(monkeypatch, envelope([{}]))
    client.get("status")
    with pytest.raises(af.BudgetExhausted):
        client.get("leagues")


# --- auth and errors -------------------------------------------------------
def test_a_short_key_is_treated_as_direct(client):
    assert not client.via_rapidapi
    assert client.base == af.DIRECT_BASE
    assert "x-apisports-key" in client.headers()


def test_a_long_key_is_treated_as_rapidapi(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "msh" + "a" * 60 + "jsn")
    other = af.Client()
    assert other.via_rapidapi
    assert other.headers()["x-rapidapi-host"] == af.RAPID_HOST


def test_errors_in_the_body_are_raised_even_with_a_200(client, monkeypatch):
    """The API reports problems in the payload, not the status code."""
    stub(monkeypatch, envelope([], errors={"token": "invalid api key"}))
    with pytest.raises(af.ApiFootballError) as exc:
        client.get("status")
    assert "invalid api key" in str(exc.value)


def test_a_401_says_the_key_is_wrong(client, monkeypatch):
    stub(monkeypatch, {"message": "Invalid API key"}, status=401)
    with pytest.raises(af.ApiFootballError) as exc:
        client.get("status")
    text = str(exc.value)
    assert "Invalid API key" in text, "the API's own reason must survive"
    assert "check .env against your dashboard" in text


def test_an_unrecognised_401_still_gets_generic_advice(client, monkeypatch):
    """No matching message, so fall back to what a 401 generally means."""
    stub(monkeypatch, {"message": "Something new and unhelpful"}, status=401)
    with pytest.raises(af.ApiFootballError) as exc:
        client.get("status")
    assert "typo" in str(exc.value)


def test_a_403_lists_the_likely_causes_in_order(client, monkeypatch):
    """403 is not the same as 401, and the difference is what to do next."""
    stub(monkeypatch, {"message": "Forbidden"}, status=403)
    with pytest.raises(af.ApiFootballError) as exc:
        client.get("status")
    text = str(exc.value)
    assert "Forbidden" in text
    assert "not been confirmed" in text
    assert "--via rapidapi" in text


def test_an_html_page_is_identified_as_an_intermediary(client, monkeypatch):
    """An HTML body means something in front of the API answered, not the API."""
    class HtmlResponse:
        status_code = 403
        headers = {}

        @staticmethod
        def json():
            raise ValueError("not json")

        text = "<!DOCTYPE html><html><body>Access denied</body></html>"

    monkeypatch.setattr(af.requests, "get",
                        lambda *a, **k: HtmlResponse())
    with pytest.raises(af.ApiFootballError) as exc:
        client.get("status")
    assert "between you and the API" in str(exc.value)


def test_we_identify_ourselves_to_the_cdn(client):
    """A bare python-requests user agent is a common blanket-403 trigger."""
    assert "python-requests" not in client.headers().get("User-Agent", "")
    assert client.headers()["User-Agent"]


def test_the_shopfront_can_be_forced(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "short-direct-key-123456")
    assert af.Client(via="rapidapi").via_rapidapi is True
    assert af.Client(via="direct").via_rapidapi is False
    assert af.Client().via_rapidapi is False          # falls back to the guess


def test_the_key_never_appears_in_an_error(client, monkeypatch):
    stub(monkeypatch, {}, status=500)
    with pytest.raises(af.ApiFootballError) as exc:
        client.get("status")
    assert client.key not in str(exc.value)


# --- league discovery ------------------------------------------------------
CATALOGUE = [
    {"league": {"id": 39, "name": "Premier League"}, "country": {"name": "England"},
     "seasons": [{"year": 2026, "current": True}]},
    {"league": {"id": 40, "name": "Championship"}, "country": {"name": "England"},
     "seasons": [{"year": 2026, "current": True}]},
    {"league": {"id": 43, "name": "National League"}, "country": {"name": "England"},
     "seasons": [{"year": 2026, "current": True}]},
    {"league": {"id": 44, "name": "National League - North"},
     "country": {"name": "England"}, "seasons": [{"year": 2026, "current": True}]},
    {"league": {"id": 179, "name": "Premiership"}, "country": {"name": "Scotland"},
     "seasons": [{"year": 2026, "current": True}]},
    {"league": {"id": 180, "name": "Championship"}, "country": {"name": "Scotland"},
     "seasons": [{"year": 2026, "current": True}]},
    {"league": {"id": 78, "name": "Bundesliga"}, "country": {"name": "Germany"},
     "seasons": [{"year": 2026, "current": True}]},
    {"league": {"id": 79, "name": "2. Bundesliga"}, "country": {"name": "Germany"},
     "seasons": [{"year": 2026, "current": True}]},
    {"league": {"id": 2, "name": "UEFA Champions League"}, "country": {"name": "World"},
     "seasons": [{"year": 2026, "current": True}]},
]


def test_leagues_map_to_the_right_ids(client, monkeypatch):
    stub(monkeypatch, envelope(CATALOGUE))
    found = af.discover_leagues(client, codes=["E0", "E1", "EC", "SC0", "D1", "D2", "UCL"])
    assert found["E0"].api_id == 39
    assert found["E1"].api_id == 40
    assert found["EC"].api_id == 43, "matched the North feeder league instead"
    assert found["SC0"].api_id == 179
    assert found["D1"].api_id == 78
    assert found["D2"].api_id == 79
    assert found["UCL"].api_id == 2
    assert all(m.confident for m in found.values())


def test_the_same_name_in_two_countries_does_not_cross_over(client, monkeypatch):
    """England and Scotland both have a "Championship". They are not the same."""
    stub(monkeypatch, envelope(CATALOGUE))
    found = af.discover_leagues(client, codes=["E1", "SC1"])
    assert found["E1"].api_id == 40
    assert found["SC1"].api_id == 180
    assert found["E1"].api_id != found["SC1"].api_id


def test_a_missing_competition_is_reported_not_guessed(client, monkeypatch):
    stub(monkeypatch, envelope([c for c in CATALOGUE
                                if c["league"]["name"] != "Premier League"]))
    found = af.discover_leagues(client, codes=["E0"])
    assert not found["E0"].confident
    assert found["E0"].note


def test_near_misses_are_recorded_for_review(client, monkeypatch):
    stub(monkeypatch, envelope(CATALOGUE))
    found = af.discover_leagues(client, codes=["EC"])
    names = [name for name, _, _ in found["EC"].alternatives]
    assert any("North" in name for name in names)


def test_the_map_survives_a_round_trip(conn, client, monkeypatch):
    stub(monkeypatch, envelope(CATALOGUE))
    found = af.discover_leagues(client, codes=["E0", "D1"])
    af.save_league_map(conn, found)
    assert af.league_id(conn, "E0") == 39
    assert af.league_id(conn, "D1") == 78
    assert af.league_id(conn, "SP1") is None


# --- fixtures --------------------------------------------------------------
def fixture_entry(api_id=1001, status="FT", hg=2, ag=1,
                  date="2026-08-29T14:00:00+00:00", league=39):
    return {
        "fixture": {"id": api_id, "referee": "M Oliver",
                    "date": date, "status": {"short": status}},
        "league": {"id": league, "season": 2026, "round": "Regular Season - 2"},
        "teams": {"home": {"name": "Liverpool"}, "away": {"name": "Nottingham Forest"}},
        "goals": {"home": hg, "away": ag},
        "score": {"halftime": {"home": 1, "away": 0}},
    }


@pytest.fixture
def mapped(conn, client, monkeypatch):
    stub(monkeypatch, envelope(CATALOGUE))
    af.save_league_map(conn, af.discover_leagues(client, codes=["E0"]))
    return conn


def test_a_finished_fixture_becomes_a_result(mapped, client, monkeypatch):
    stub(monkeypatch, envelope([fixture_entry()]))
    af.load_fixtures(mapped, client, "2026/27", date="2026-08-29")
    row = mapped.execute("SELECT fthg, ftag, status, referee, api_fixture_id "
                         "FROM matches").fetchone()
    assert (row["fthg"], row["ftag"], row["status"]) == (2, 1, "played")
    assert row["referee"] == "M Oliver"
    assert row["api_fixture_id"] == 1001


def test_an_unplayed_fixture_stays_a_fixture(mapped, client, monkeypatch):
    stub(monkeypatch, envelope([fixture_entry(status="NS", hg=None, ag=None)]))
    af.load_fixtures(mapped, client, "2026/27", date="2026-08-29")
    row = mapped.execute("SELECT fthg, status FROM matches").fetchone()
    assert row["fthg"] is None and row["status"] == "scheduled"


def test_a_postponed_fixture_is_skipped(mapped, client, monkeypatch):
    stub(monkeypatch, envelope([fixture_entry(status="PST")]))
    af.load_fixtures(mapped, client, "2026/27", date="2026-08-29")
    assert mapped.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0


def test_competitions_we_do_not_follow_are_ignored(mapped, client, monkeypatch):
    """Asking by date returns the whole world; we want our leagues only."""
    stub(monkeypatch, envelope([fixture_entry(league=61)]))
    af.load_fixtures(mapped, client, "2026/27", date="2026-08-29")
    assert mapped.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0


def test_a_richer_result_is_not_overwritten_but_gains_its_fixture_id(mapped, client,
                                                                     monkeypatch):
    from vb.repo import upsert_match

    match_id = upsert_match(mapped, "E0", "2026/27", "2026-08-29T14:00:00",
                            "Liverpool", "Nottingham Forest",
                            fthg=3, ftag=3, hs=20, hc=11, source="football-data")
    stub(monkeypatch, envelope([fixture_entry(hg=2, ag=1)]))
    af.load_fixtures(mapped, client, "2026/27", date="2026-08-29")
    row = mapped.execute("SELECT fthg, ftag, hs, hc, api_fixture_id FROM matches "
                         "WHERE id = ?", (match_id,)).fetchone()
    assert (row["fthg"], row["ftag"], row["hs"], row["hc"]) == (3, 3, 20, 11)
    assert row["api_fixture_id"] == 1001, "we still need their id to ask for stats"
    assert mapped.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1


# --- injuries --------------------------------------------------------------
def injury(name="A Player", team="Liverpool", kind="Missing Fixture",
           reason="Knee Injury", date="2030-01-01T00:00:00+00:00"):
    return {"player": {"name": name}, "team": {"name": team},
            "fixture": {"date": date}, "type": kind, "reason": reason}


def test_injuries_become_team_news(mapped, client, monkeypatch):
    stub(monkeypatch, envelope([injury()]))
    af.load_injuries(mapped, client, "2026/27", codes=["E0"])
    row = mapped.execute("SELECT player, kind, impact, source FROM team_news").fetchone()
    assert row["player"] == "A Player"
    assert row["kind"] == "injury"
    assert row["impact"] > 0
    assert row["source"] == "api-football"


def test_a_suspension_is_not_filed_as_an_injury(mapped, client, monkeypatch):
    """A suspended player is certainly out; an injured one might recover."""
    stub(monkeypatch, envelope([injury(reason="Red card suspension")]))
    af.load_injuries(mapped, client, "2026/27", codes=["E0"])
    assert mapped.execute("SELECT kind FROM team_news").fetchone()["kind"] == "suspension"


def test_a_doubt_counts_for_less_than_an_absence(mapped, client, monkeypatch):
    stub(monkeypatch, envelope([injury(kind="Questionable", reason="Illness")]))
    af.load_injuries(mapped, client, "2026/27", codes=["E0"])
    row = mapped.execute("SELECT kind, impact FROM team_news").fetchone()
    assert row["kind"] == "doubt"
    assert row["impact"] < af.INJURY_KINDS["missing fixture"][1]


def test_the_same_absence_is_not_recorded_twice(mapped, client, monkeypatch):
    stub(monkeypatch, envelope([injury()]))
    af.load_injuries(mapped, client, "2026/27", codes=["E0"])
    af.load_injuries(mapped, client, "2026/27", codes=["E0"])
    assert mapped.execute("SELECT COUNT(*) FROM team_news").fetchone()[0] == 1


def test_news_about_a_match_already_played_is_ignored(mapped, client, monkeypatch):
    stub(monkeypatch, envelope([injury(date="2020-01-01T00:00:00+00:00")]))
    af.load_injuries(mapped, client, "2026/27", codes=["E0"])
    assert mapped.execute("SELECT COUNT(*) FROM team_news").fetchone()[0] == 0


# --- statistics ------------------------------------------------------------
def test_statistics_land_in_the_right_columns(mapped, client, monkeypatch):
    from vb.repo import upsert_match

    match_id = upsert_match(mapped, "E0", "2026/27", "2026-08-29T14:00:00",
                            "Liverpool", "Nottingham Forest", fthg=2, ftag=1,
                            api_fixture_id=1001, source="api-football")
    stub(monkeypatch, envelope([
        {"team": {"name": "Liverpool"}, "statistics": [
            {"type": "Shots on Goal", "value": 7}, {"type": "Total Shots", "value": 18},
            {"type": "Corner Kicks", "value": 9}, {"type": "Yellow Cards", "value": 1},
            {"type": "expected_goals", "value": "2.41"}]},
        {"team": {"name": "Nottingham Forest"}, "statistics": [
            {"type": "Shots on Goal", "value": 3}, {"type": "Total Shots", "value": 8},
            {"type": "Corner Kicks", "value": 2}, {"type": "Yellow Cards", "value": 3},
            {"type": "expected_goals", "value": "0.88"}]},
    ]))
    assert af.load_statistics(mapped, client, [(match_id, 1001)]) == 1
    row = mapped.execute('SELECT hst, ast, hs, "as", hc, ac, hy, ay, home_xg, away_xg '
                         "FROM matches WHERE id = ?", (match_id,)).fetchone()
    assert (row["hst"], row["ast"]) == (7, 3)
    assert (row["hs"], row["as"]) == (18, 8)
    assert (row["hc"], row["ac"]) == (9, 2)
    assert (row["hy"], row["ay"]) == (1, 3)
    assert row["home_xg"] == pytest.approx(2.41)


def test_only_matches_with_a_fixture_id_and_no_stats_are_queued(mapped):
    from vb.repo import upsert_match

    wanted = upsert_match(mapped, "E0", "2026/27", "2026-08-29T14:00:00",
                          "Alpha", "Beta", fthg=1, ftag=0, api_fixture_id=5001,
                          source="api-football")
    upsert_match(mapped, "E0", "2026/27", "2026-08-29T14:00:00", "Gamma", "Delta",
                 fthg=1, ftag=0, hst=4, ast=2, api_fixture_id=5002,
                 source="api-football")          # already has shots
    upsert_match(mapped, "E0", "2026/27", "2026-08-29T14:00:00", "Epsilon", "Zeta",
                 fthg=1, ftag=0, source="football-data")   # no fixture id
    queued = af.matches_needing_statistics(mapped)
    assert [m for m, _ in queued] == [wanted]


def test_the_not_subscribed_message_names_the_actual_fix(client, monkeypatch):
    """RapidAPI's wording for a key that is not one of theirs at all."""
    stub(monkeypatch, {"message": "You are not subscribed to this API."}, status=403)
    with pytest.raises(af.ApiFootballError) as exc:
        client.get("status")
    text = str(exc.value)
    assert "--via direct" in text
    assert "Subscribe" in text
    assert "email" not in text, "the generic guesses should be replaced, not appended"


def test_a_forced_shopfront_is_labelled_as_forced(monkeypatch):
    """When diagnosing, 'detected' and 'you told me' are different facts."""
    monkeypatch.setenv("API_FOOTBALL_KEY", "short-direct-key-123456")
    assert "forced" in af.Client(via="rapidapi").shopfront
    assert "forced" not in af.Client().shopfront


# --- telling the user which key is actually being used ---------------------
def test_the_fingerprint_shows_enough_to_recognise_but_not_to_use(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "14850bb134783e29592b004ed66df647")
    client = af.Client()
    printed = client.key_fingerprint()
    assert "1485" in printed and "f647" in printed
    assert "32 characters" in printed
    assert client.key not in printed, "the whole key must never be printed"


def test_a_short_key_is_called_out(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "abc123")
    assert "too short" in af.Client().key_fingerprint()


def test_the_placeholder_is_rejected_before_any_request(monkeypatch):
    """Copying .env.example and forgetting to edit it is an easy miss."""
    monkeypatch.setenv("API_FOOTBALL_KEY", "paste-your-key-here")
    with pytest.raises(af.MissingKey) as exc:
        af.Client()
    assert "placeholder" in str(exc.value)


def test_a_wrong_length_key_is_flagged_before_it_is_blamed(conn, monkeypatch):
    """A 20-character "direct" key explains itself without a round trip."""
    monkeypatch.setenv("API_FOOTBALL_KEY", "far-too-short-abc123")
    client = af.Client(via="direct")
    stub(monkeypatch, envelope([{"subscription": {"plan": "Free"}}]))
    monkeypatch.setattr(af, "discover_leagues", lambda *a, **k: {})
    report = af.check(conn, client, "2026/27")
    assert "32 characters" in report["key_warning"]
