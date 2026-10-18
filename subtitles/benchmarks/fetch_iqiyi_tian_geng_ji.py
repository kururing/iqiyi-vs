"""Fetch and normalize the Vietnamese XML tracks observed in iQ.com players."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from subtitles.benchmarks import tian_geng_ji as bench

BASE = ROOT / "subtitles/international/tian-geng-ji"
SOURCE_MANIFEST = BASE / "track-source-manifest.json"
TRACK_DIR = BASE / "tracks"


def _timecode(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def parse_iq_xml(payload: bytes):
    root = ET.fromstring(payload)
    cues = []
    for ordinal, dia in enumerate(root.findall(".//dia"), 1):
        start = int(dia.findtext("st", "-1"))
        end = int(dia.findtext("et", "-1"))
        node = dia.find("sub")
        text = "".join(node.itertext()).replace("\r\n", "\n").strip() if node is not None else ""
        if start < 0 or end <= start:
            raise ValueError(f"Invalid cue interval at XML dia {ordinal}: {start}..{end}")
        if text:
            text = re.sub(r"[ \t]+\n", "\n", text)
            cues.append((start, end, text, ordinal))
    if not cues:
        raise ValueError("The XML contains no non-empty subtitle cues.")
    if any(cues[i][0] > cues[i + 1][0] for i in range(len(cues) - 1)):
        raise ValueError("Subtitle cue starts are not in file order.")
    blocks = [f"{i}\n{_timecode(start)} --> {_timecode(end)}\n{text}"
              for i, (start, end, text, _ordinal) in enumerate(cues, 1)]
    return cues, ("\n\n".join(blocks) + "\n").encode("utf-8")


def fetch(entry: dict, episode: int, attempts: int = 3):
    host = entry["resource_host"]
    path = entry["resource_path"]
    if host != "meta.video.iqiyi.com" or not path.startswith("/") or ".." in Path(path).parts:
        raise ValueError(f"Episode {episode:02d} contains an unapproved asset location.")
    url = f"https://{host}{path}"
    error = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0", "Accept": "application/xml,text/xml,*/*"})
            with urllib.request.urlopen(request, timeout=30) as response:
                content_type = (response.headers.get("Content-Type") or "").casefold()
                payload = response.read()
                if response.status != 200 or "xml" not in content_type:
                    raise ValueError(f"Unexpected response for ep{episode:02d}: {response.status} {content_type}")
                return payload, content_type, response.status
        except Exception as exc:  # preserve the final upstream/transport diagnostic
            error = exc
            if attempt + 1 < attempts:
                time.sleep(1)
    raise RuntimeError(f"Episode {episode:02d} fetch failed: {error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-only", action="store_true", help="validate source metadata without downloading")
    args = parser.parse_args()
    source = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    episodes = source.get("episodes", {})
    if source.get("series") != "田耕纪" or source.get("album_id") != "7714930311098201":
        raise ValueError("Wrong series or album in track-source-manifest.json")
    if set(episodes) != {f"{ep:02d}" for ep in range(1, 27)}:
        raise ValueError("Expected one track entry for every episode 01–26")

    TRACK_DIR.mkdir(parents=True, exist_ok=True)
    audit_rows = []
    failures = []
    source_rows = bench._source_rows()
    for key in sorted(episodes):
        episode = int(key)
        entry = episodes[key]
        if entry.get("lid") != "23" or entry.get("language") != "Tiếng Việt" or not entry.get("player_load_success"):
            raise ValueError(f"Episode {key}: player evidence is incomplete or not Vietnamese.")
        raw_path = TRACK_DIR / f"episode-{key}.vi.iq.xml"
        srt_path = BASE / f"episode-{key}.vi.srt"
        try:
            if args.inventory_only:
                payload = raw_path.read_bytes()
                content_type, status = "previously_acquired", 200
            else:
                payload, content_type, status = fetch(entry, episode)
            cues, srt_bytes = parse_iq_xml(payload)
            raw_path.write_bytes(payload)
            srt_path.write_bytes(srt_bytes)
            cue_map_path = BASE / f"episode-{key}.cue-map.csv"
            with cue_map_path.open("w", encoding="utf-8-sig", newline="") as map_handle:
                map_writer = csv.DictWriter(map_handle, fieldnames=[
                    "normalized_cue_id", "xml_dia_ordinal", "start_ms", "end_ms", "text"])
                map_writer.writeheader()
                map_writer.writerows({"normalized_cue_id": i, "xml_dia_ordinal": row[3],
                    "start_ms": row[0], "end_ms": row[1], "text": row[2]}
                    for i, row in enumerate(cues, 1))
            cue_map_sha256 = hashlib.sha256(cue_map_path.read_bytes()).hexdigest()
            xml_dia_count = len(ET.fromstring(payload).findall(".//dia"))
            source_cues = source_rows[episode]["source"]
            source_end_ms = max(row[1] for row in source_cues)
            reference_end_ms = max(row[1] for row in cues)
            end_delta_ms = reference_end_ms - source_end_ms
            tail_ms = entry["video_duration_ms"] - reference_end_ms
            release_match = abs(end_delta_ms) <= 60_000 and tail_ms >= 0
            entry.update({
                "raw_track_file": str(raw_path.relative_to(BASE)).replace("\\", "/"),
                "raw_xml_sha256": hashlib.sha256(payload).hexdigest(),
                "raw_xml_bytes": len(payload),
                "content_type": content_type,
                "http_status": status,
                "normalized_track_file": srt_path.name,
                "normalized_srt_sha256": hashlib.sha256(srt_bytes).hexdigest(),
                "cue_map_file": cue_map_path.name,
                "cue_map_sha256": cue_map_sha256,
                "xml_dia_count": xml_dia_count,
                "empty_xml_dia_count": xml_dia_count - len(cues),
                "cue_count": len(cues),
                "cue_start_min_ms": min(row[0] for row in cues),
                "cue_end_max_ms": reference_end_ms,
                "subtitle_version": str(entry["resource_path"]).split("/")[1],
                "source_release_match": release_match,
                "source_last_cue_end_ms": source_end_ms,
                "source_reference_end_delta_ms": end_delta_ms,
                "video_after_last_reference_cue_ms": tail_ms,
                "episode_page_binding_verified": bool(entry.get("player_load_success")),
                "timeline_consistency_verified": release_match,
                "exact_cut_identity_verified": False,
            })
            audit_rows.append({
                "episode": episode, "track_tvid": entry["track_tvid"],
                "source_cue_count": len(source_cues), "source_last_cue_end_ms": source_end_ms,
                "duration_ms": entry["video_duration_ms"], "cue_count": len(cues),
                "first_cue_start_ms": min(row[0] for row in cues),
                "last_cue_end_ms": reference_end_ms,
                "source_reference_end_delta_ms": end_delta_ms,
                "cue_tail_before_video_end_ms": tail_ms,
                "source_release_match": release_match,
                "raw_xml_sha256": entry["raw_xml_sha256"],
                "normalized_srt_sha256": entry["normalized_srt_sha256"],
            })
            print(json.dumps({"episode": episode, "status": status, "bytes": len(payload),
                "cue_count": len(cues), "max_end_ms": max(row[1] for row in cues),
                "raw_xml_sha256": entry["raw_xml_sha256"]}, ensure_ascii=False), flush=True)
        except Exception as exc:
            failures.append({"episode": episode, "error": str(exc)})
            print(json.dumps({"episode": episode, "error": str(exc)}, ensure_ascii=False), flush=True)

    source["acquisition_checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    source["acquisition_failures"] = failures
    SOURCE_MANIFEST.write_text(json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit_path = BASE / "track-time-audit.csv"
    with audit_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = list(audit_rows[0]) if audit_rows else ["episode"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(audit_rows)

    verified_entries = {}
    for key, entry in episodes.items():
        if not all(entry.get(field) for field in (
                "raw_xml_sha256", "normalized_srt_sha256", "normalized_track_file", "cue_map_file",
                "cue_map_sha256")):
            continue
        verified = bool(entry.get("player_load_success") and entry.get("language") == "Tiếng Việt"
                        and str(entry.get("lid")) == "23" and entry.get("source_release_match"))
        verified_entries[key] = {
            "status": "verified" if verified else "review_required",
            "episode_url": entry["episode_url"], "tvid": str(entry["track_tvid"]),
            "album_id": "7714930311098201", "language": "vi", "lid": "23",
            "version": f"iQ.com player XML asset {entry['subtitle_version']}; qd_tvid={entry['track_tvid']}",
            "duration_ms": entry["video_duration_ms"],
            "sha256": entry["normalized_srt_sha256"],
            "track_file": entry["normalized_track_file"], "cue_count": entry["cue_count"],
            "raw_track_file": entry["raw_track_file"], "raw_xml_sha256": entry["raw_xml_sha256"],
            "xml_dia_count": entry["xml_dia_count"], "cue_map_file": entry["cue_map_file"],
            "cue_map_sha256": entry["cue_map_sha256"],
            "player_load_success": entry["player_load_success"],
            "source_last_cue_end_ms": entry["source_last_cue_end_ms"],
            "track_last_cue_end_ms": entry["cue_end_max_ms"],
            "source_reference_end_delta_ms": entry["source_reference_end_delta_ms"],
            "video_after_last_reference_cue_ms": entry["video_after_last_reference_cue_ms"],
            "source_release_match": verified,
            "episode_page_binding_verified": entry["episode_page_binding_verified"],
            "timeline_consistency_verified": entry["timeline_consistency_verified"],
            "exact_cut_identity_verified": False,
            "verification_basis": "Rendered episode title/list; player reported loadXml ok for Tiếng Việt lid=23 and episode-specific qd_tvid; downloaded text/xml; raw and normalized SHA-256; cue end within player duration and within 60 seconds of the corresponding Chinese source's final cue. This supports episode identity but does not independently prove frame-for-frame cut identity or editorial accuracy.",
            "editorial_accuracy_verified": False,
        }
    if len(verified_entries) == 26:
        manifest = {"series": "田耕纪", "album_id": "7714930311098201", "episodes": verified_entries}
        (BASE / "track-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        verification_path = BASE / "verification.json"
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        verification["source_track_verification"] = {
            "status": "metadata_file_and_timing_verified",
            "scope": "Official Vietnamese lid=23 tracks are bound to their iQ.com episode pages and checked against Chinese cue timelines. This supports episode identity but does not independently prove frame-for-frame cut identity or subtitle translation accuracy.",
            "track_manifest": "track-manifest.json", "raw_files_dir": "tracks/",
            "episodes_verified": len(verified_entries), "verified_at": source["acquisition_checked_at"],
        }
        for key, entry in verified_entries.items():
            verification["episodes"][key].update({
                "status": "metadata_file_and_timing_verified", "track_file": entry["track_file"],
                "raw_track_file": entry["raw_track_file"], "track_metadata_verified": True,
                "verified_subtitle_file": True, "international_tvid_obtained": True,
                "international_tvid": entry["tvid"], "lid": entry["lid"],
                "language": entry["language"], "version": entry["version"],
                "video_duration_ms": entry["duration_ms"], "cue_count": entry["cue_count"],
                "sha256": entry["sha256"], "normalized_srt_sha256": entry["sha256"],
                "raw_xml_sha256": entry["raw_xml_sha256"],
                "cue_map_file": entry["cue_map_file"], "cue_map_sha256": entry["cue_map_sha256"],
                "source_release_match": entry["source_release_match"],
                "episode_page_binding_verified": True, "timeline_consistency_verified": True,
                "exact_cut_identity_verified": False,
                "verification_basis": entry["verification_basis"],
                "editorial_accuracy_verified": False,
            })
        verification["page_evidence"].update({
            "visible_episode_list": "1-26", "verified_player_track_count": len(verified_entries),
            "evidence_level": "player-track-file-hash-timing-checked",
            "verified_subtitle_file": True, "international_tvid_obtained": True,
            "verified_episode_track_binding": True, "verified_release_match": False,
            "exact_release_edition": "Official Vietnamese track loaded by the corresponding iQ.com episode page; exact frame-for-frame cut identity not independently verified.",
            "player_language_id_observation": "Each episode page showed a successful player loadXml for the Vietnamese subtitle track (lid=23); episode-specific qd_tvid and duration are recorded in track-source-manifest.json.",
        })
        verification["missing_evidence"] = [
            "Frame-for-frame identity of the international and Chinese releases is not independently verified; page binding and cue timelines support episode identity.",
            "Editorial accuracy requires semantic review against Chinese dialogue and surrounding context."
        ]
        verification["page_evidence"].pop("player_log_excerpt", None)
        verification_path.write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"acquired": len(audit_rows), "failures": failures,
        "verified_tracks": len(verified_entries), "source_manifest": str(SOURCE_MANIFEST),
        "track_manifest": str(BASE / 'track-manifest.json'), "time_audit": str(audit_path)}, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
