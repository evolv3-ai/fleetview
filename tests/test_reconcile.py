from fleetview.reconcile import ReconcileReport, format_report, reconcile


def _stack(resource, project="base", running=True, platform=False, image="img:1"):
    return {"kind": "coolify-service", "project": project, "environment": "production",
            "resource": resource, "coolifyUuid": None, "domains": [], "workingDir": None,
            "platform": platform,
            "containers": [{"name": resource, "image": image,
                            "state": "running" if running else "exited", "health": None,
                            "restartCount": 0}]}


SNAPSHOT = {"generatedAt": "x", "servers": {
    "cbo-01-217-110": {"fetchedAt": "x", "sentinel": {"mode": "coolify", "version": "1.1.5"}, "stacks": {
        "uuidtracked": _stack("providentls"),
        "uuiduntracked": _stack("mystery-app"),
        "uuidjelly": _stack("jellyfin", image="jellyfin/jellyfin:10"),
        "uuidstopped": _stack("old-thing", running=False),
        "coolify-proxy": _stack(None, project=None, platform=True),
    }},
}}

PROFILE = {
    "servers": [
        {"id": "cbo-01-217-110", "apps": ["jellyfin-12.2", "affine", "coolify-4.3.23"]},
        {"id": "htz-09-1-1", "apps": ["ghost"]},  # not in the snapshot: ignored
        {"name": "legacy-entry-without-id"},
    ],
    "deployments": {
        "cbo-01-providentls-app": {"type": "coolify", "serverIds": ["cbo-01-217-110"], "stackKey": "uuidtracked"},
        "cbo-01-gone": {"type": "coolify", "serverIds": ["cbo-01-217-110"], "stackKey": "uuidgone"},
        "cbo-01-old": {"type": "coolify", "serverIds": ["cbo-01-217-110"], "stackKey": "uuidstopped"},
        "orbit-like": {"serverId": "cbo-01-217-110", "coolifyAppUuid": "uuidjelly"},
        "elsewhere": {"serverIds": ["htz-09-1-1"], "stackKey": "zzz"},
        "no-key": {"serverIds": ["cbo-01-217-110"]},
    },
}


def test_reconcile_reports_untracked_missing_and_drift():
    r = reconcile(SNAPSHOT, PROFILE)
    assert isinstance(r, ReconcileReport)
    assert r.untracked == [("cbo-01-217-110", "uuiduntracked", "mystery-app")]
    assert r.missing == [("cbo-01-gone", "uuidgone")]
    assert r.not_running == [("cbo-01-old", "uuidstopped")]
    assert r.apps_drift == [("cbo-01-217-110", "affine"), ("cbo-01-217-110", "coolify-4.3.23")]
    assert ("cbo-01-217-110", "jellyfin-12.2") not in r.apps_drift
    assert all(srv == "cbo-01-217-110" for srv, _ in r.apps_drift)


def test_format_report_sections():
    text = format_report(reconcile(SNAPSHOT, PROFILE))
    for head in ("Untracked stacks (1)", "Missing deployments (1)", "Not running (1)", "Apps drift ("):
        assert head in text
    empty = format_report(ReconcileReport([], [], [], []))
    assert empty.count("none") == 4
