#!/usr/bin/env python3
"""Offside Talk YouTube runner (no Zapier).

Runs inside GitHub Actions. Every jobs/<id>.json that has no results/<id>.json yet is
processed and its result written to results/<id>.json. Uses only the Python stdlib.

Secrets (repo Settings -> Secrets and variables -> Actions):
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN

Job format:
{
  "requests": [                      # optional: plain YouTube Data API calls, run in order
    {"name": "s1", "method": "GET", "path": "search", "params": {...}},
    {"name": "c1", "method": "POST", "path": "comments", "params": {"part": "snippet"}, "body": {...}}
  ],
  "upload": {                        # optional: publish a video
    "video": "videos/<slug>.mp4",    # repo path
    "thumbnail": "thumbs/<slug>.jpg",
    "snippet": {...}, "status": {...}, "localizations": {...},
    "first_comment": "text"
  }
}
Only https://www.googleapis.com/youtube/v3/ endpoints can be called.
"""
import glob, json, os, sys, time, urllib.error, urllib.parse, urllib.request

API = "https://www.googleapis.com/youtube/v3/"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/"


def http(method, url, data=None, headers=None, timeout=600):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, dict(r.headers), raw
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def as_json(raw):
    try:
        return json.loads(raw or b"{}")
    except Exception:
        return {"raw": raw.decode("utf-8", "replace")[:2000]}


def token():
    need = ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        raise RuntimeError("setup_missing: secrets not set: " + ", ".join(missing))
    body = urllib.parse.urlencode({
        "client_id": os.environ["YT_CLIENT_ID"],
        "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    st, _, raw = http("POST", "https://oauth2.googleapis.com/token", body,
                      {"Content-Type": "application/x-www-form-urlencoded"}, 60)
    j = as_json(raw)
    if st != 200 or "access_token" not in j:
        raise RuntimeError(f"auth_error: token refresh failed ({st}): {j}")
    return j["access_token"]


def call(tok, method, path, params=None, body=None):
    path = path.lstrip("/")
    if path.startswith("http"):
        if not path.startswith(API):
            return 400, {"error": "only youtube/v3 endpoints are allowed"}
        url = path
    else:
        url = API + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = {"Authorization": "Bearer " + tok}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    st, _, raw = http(method.upper(), url, data, h, 120)
    return st, as_json(raw)


def upload(tok, u, repo):
    out = {}
    path = os.path.join(repo, u["video"])
    size = os.path.getsize(path)
    meta = {"snippet": u["snippet"], "status": u.get("status", {})}
    parts = "snippet,status"
    if u.get("localizations"):
        meta["localizations"] = u["localizations"]
        parts += ",localizations"
    st, hd, raw = http("POST", UPLOAD + "videos?uploadType=resumable&part=" + parts,
                       json.dumps(meta).encode(), {
                           "Authorization": "Bearer " + tok,
                           "Content-Type": "application/json; charset=UTF-8",
                           "X-Upload-Content-Type": "video/mp4",
                           "X-Upload-Content-Length": str(size)}, 120)
    loc = {k.lower(): v for k, v in hd.items()}.get("location")
    if st != 200 or not loc:
        out["upload"] = {"ok": False, "status": st, "error": as_json(raw)}
        return out
    with open(path, "rb") as f:
        data = f.read()
    res = None
    for attempt in range(3):
        st, _, raw = http("PUT", loc, data, {"Content-Type": "video/mp4",
                                             "Content-Length": str(size)}, 1800)
        res = as_json(raw)
        if st in (200, 201):
            break
        time.sleep(10)
    if st not in (200, 201):
        out["upload"] = {"ok": False, "status": st, "error": res}
        return out
    vid = res.get("id")
    out["upload"] = {"ok": True, "id": vid, "uploadStatus": res.get("status", {}).get("uploadStatus"),
                     "url": f"https://www.youtube.com/watch?v={vid}"}
    # privacy check: unverified API projects get uploads locked to private
    st, j = call(tok, "GET", "videos", {"part": "status", "id": vid})
    items = j.get("items") or [{}]
    out["privacy"] = items[0].get("status", {})
    out["locked_private"] = (u.get("status", {}).get("privacyStatus") == "public"
                             and out["privacy"].get("privacyStatus") != "public")
    if u.get("thumbnail"):
        tp = os.path.join(repo, u["thumbnail"])
        with open(tp, "rb") as f:
            img = f.read()
        st, _, raw = http("POST", UPLOAD + "thumbnails/set?uploadType=media&videoId=" + vid, img,
                          {"Authorization": "Bearer " + tok, "Content-Type": "image/jpeg"}, 120)
        out["thumbnail"] = {"ok": st == 200, "status": st, "resp": as_json(raw)}
    if u.get("first_comment"):
        st, j = call(tok, "POST", "commentThreads", {"part": "snippet"}, {"snippet": {
            "videoId": vid, "topLevelComment": {"snippet": {"textOriginal": u["first_comment"]}}}})
        out["first_comment"] = {"ok": st == 200, "status": st, "id": j.get("id"), "error": j.get("error")}
    return out


def run_job(job, repo):
    res = {"ok": True, "finished": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        tok = token()
    except Exception as e:
        return {"ok": False, "error": str(e), "finished": res["finished"]}
    reqs = []
    for r in job.get("requests", []):
        st, j = call(tok, r.get("method", "GET"), r["path"], r.get("params"), r.get("body"))
        reqs.append({"name": r.get("name"), "status": st, "response": j})
    if reqs:
        res["requests"] = reqs
    if job.get("upload"):
        try:
            res.update(upload(tok, job["upload"], repo))
        except Exception as e:
            res["upload"] = {"ok": False, "error": repr(e)}
        res["ok"] = res.get("upload", {}).get("ok", False)
    return res


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(os.path.join(repo, "results"), exist_ok=True)
    done = 0
    for jp in sorted(glob.glob(os.path.join(repo, "jobs", "*.json"))):
        jid = os.path.splitext(os.path.basename(jp))[0]
        rp = os.path.join(repo, "results", jid + ".json")
        if os.path.exists(rp):
            continue
        try:
            job = json.load(open(jp))
            out = run_job(job, repo)
        except Exception as e:
            out = {"ok": False, "error": "bad job: " + repr(e)}
        out["job"] = jid
        json.dump(out, open(rp, "w"), indent=1, ensure_ascii=False)
        print(jid, "ok" if out.get("ok") else "FAILED", str(out.get("error") or "")[:300])
        done += 1
    print("jobs processed:", done)


if __name__ == "__main__":
    main()
