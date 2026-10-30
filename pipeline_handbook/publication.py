"""Strict public projection of a private static scan; no source text is copied.

Aliases replace every private identifier, free-text claim and source location.
Only enumerated product facts, graph structure, numeric metrics and opaque hashes
survive. The private reverse mapping must never enter a publication bundle.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re

from .architecture import recover
from .config import DATA, DEFAULTS, _merge
from .model import NODE_KINDS, EDGE_KINDS
from .registry import Registry
from .security import digest, safe_json, stable_id

PROFILE = "ncbs-anonymized/v1"
POLICY = "strict-alias-projection/v1"
NOTICE = "Private source and object names replaced by stable aliases; original hashes retained."
PROJECT = "NCBS compatibility case study — anonymized static definitions"
CONFIG = {"mode": "static-public-projection", "paths": "withheld", "network_enabled": False,
          "source_code_included": False, "business_rows_included": False, "annotations_included": False}
FORMATS = {"py", "sql", "json", "xml", "ktr", "kjb", "md", "txt", "rst", "toml", "yaml", "yml", "dockerfile", "sh", "cron", "other"}
STATUSES = {"declared", "inferred", "unknown"}
CATEGORIES = {"mentioned", "declared", "recognized", "ambiguous"}
CONDITIONS = {"success", "failure", "unconditional", "completion", "service_started", "service_healthy", "service_completed_successfully"}
RELATIONS = {"startup_dependency", "network_attachment", "volume_mount", "declared_consumer", "host_placement"}
ADAPTERS = {"builtin:inventory", "builtin:detector", "builtin:sql", "builtin:pentaho", "builtin:shell", "builtin:airflow", "builtin:dbt", "builtin:compose", "builtin:environment_map", "builtin:metadata"}
RESOURCES = {"compose_service", "compose_network", "compose_volume", "component", "deployment_resource"}
SAFE_CODES = {"unknown_artifact", "unsupported_file", "data_content_skipped", "unsafe_xml", "invalid_json", "access_denied", "budget_exceeded", "symlink_skipped", "adapter_failed", "unsupported_sql", "sql_dialect_unknown", "dynamic_sql", "sql_no_supported_lineage", "sql_destination_columns_unknown", "version_conflict", "override_conflict", "unresolved_reference", "manual_conflict", "configured_technology_unseen", "compose_service_fields_unsupported", "compose_top_level_unsupported", "compose_dynamic_resource", "compose_image_unresolved", "compose_default_network_unexpanded", "compose_network_reference_unresolved", "compose_dependency_invalid", "compose_dependency_unresolved", "compose_dependency_cycle", "compose_mount_unsupported", "compose_resource_fields_unsupported", "compose_network_options_unsupported", "compose_network_mode_unsupported", "resource_filtered", "adapter_conflict", "unsupported_or_unrecognized"}
HEX = re.compile(r"[0-9a-f]+")
VERSION = re.compile(r"[0-9]{1,4}(?:\.[0-9]{1,4}){0,3}(?:(?:a|b|rc)[0-9]{1,3})?")
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)")


def _caps():
    config = _merge(DEFAULTS, {"_base": str(DATA.parent.parent), "sources": []})
    return Registry(config).capabilities()


def _enum(value, allowed, fallback):
    return value if isinstance(value, str) and value in allowed else fallback


def _stamp(value):
    return value if isinstance(value, str) and STAMP.fullmatch(value) else "1970-01-01T00:00:00Z"


def _hash(value, length):
    return value if isinstance(value, str) and len(value) == length and HEX.fullmatch(value) else digest(value)[:length]


def _aliases(values, prefix):
    return {value: f"{prefix}_{index:03d}" for index, value in enumerate(sorted(set(values)), 1)}


def _issue_text(code):
    if code == "unknown_artifact":
        return "No supported structural signature was found. Supply a supported metadata export or trusted parser."
    if code in {"unsupported_sql", "dynamic_sql", "sql_dialect_unknown", "sql_no_supported_lineage"}:
        return "SQL is outside the supported static grammar or dialect evidence; no lineage was guessed."
    if code == "version_conflict":
        return "Version declarations differ; reconcile source revisions before inferring a runtime version."
    return "A bounded inspection or parsing limit was reported. Consult its category and anonymized evidence; missing visibility does not establish absence."


def anonymize_snapshot(raw):
    """Return (public snapshot, private reverse mapping). Never publish mapping."""
    if any(node.get("status") == "observed" or node.get("kind") == "run" for node in raw.get("nodes", [])):
        raise ValueError("this publication profile accepts static definitions only")
    source_names = {source["id"] for source in raw.get("sources", [])}
    source_names.update(a["source_id"] for a in raw.get("artifacts", []))
    source_map = _aliases(source_names, "scope")
    env_map = _aliases([s["environment"] for s in raw.get("sources", [])] + [n["environment"] for n in raw.get("nodes", [])], "environment")
    namespaces = _aliases([s.get("service", s["id"]) for s in raw.get("sources", [])] + [n["namespace"] for n in raw.get("nodes", [])], "namespace")
    node_names, node_ids, artifact_ids, artifact_paths = {}, {}, {}, {}
    for kind in sorted(NODE_KINDS):
        members = sorted([n for n in raw.get("nodes", []) if n["kind"] == kind], key=lambda n: n["id"])
        for number, node in enumerate(members, 1):
            name = f"{kind}_{number:03d}"
            node_names[node["id"]] = name
            node_ids[node["id"]] = stable_id(kind, env_map[node["environment"]], namespaces[node["namespace"]], name)
    artifacts = []
    for number, artifact in enumerate(sorted(raw.get("artifacts", []), key=lambda a: a["id"]), 1):
        fmt = _enum(artifact.get("format"), FORMATS, "other")
        path = f"artifact_{number:03d}.{fmt}"
        aid = stable_id("artifact", source_map[artifact["source_id"]], env_map[artifact["environment"]], path)
        artifact_ids[artifact["id"]], artifact_paths[artifact["id"]] = aid, path
        artifacts.append({"id": aid, "source_id": source_map[artifact["source_id"]], "environment": env_map[artifact["environment"]],
            "service": namespaces.get(artifact.get("service"), "namespace_000"), "path": path, "format": fmt,
            "size": int(artifact.get("size", 0)), "hash": _hash(artifact["hash"], 64) if artifact.get("hash") else None,
            "inspection": _enum(artifact.get("inspection"), {"metadata-only", "static-definition", "unreadable"}, "unreadable")})
    by_raw_artifact = {a["id"]: a for a in raw.get("artifacts", [])}
    rules = _aliases([e["rule_id"] for e in raw.get("evidence", [])], "rule")
    evidence_ids, evidence = {}, []
    for number, item in enumerate(sorted(raw.get("evidence", []), key=lambda e: e["id"]), 1):
        original = by_raw_artifact.get(item["artifact_id"])
        if original:
            aid = artifact_ids[original["id"]]
            line_match = re.search(r":L(\d+)$", item.get("location", ""))
            location = source_map[original["source_id"]] + "/" + artifact_paths[original["id"]] + ":L" + (line_match[1] if line_match else "1")
        else:
            aid = stable_id("scope-evidence", number)
            location = "configured-scope/[metadata]:L1"
        record = {"artifact_id": aid, "location": location, "source_hash": _hash(item["source_hash"], 64) if item.get("source_hash") else None,
            "adapter": _enum(item.get("adapter"), ADAPTERS, "builtin:metadata"), "adapter_version": item.get("adapter_version") if VERSION.fullmatch(str(item.get("adapter_version", ""))) else "0.0.0",
            "rule_id": rules[item["rule_id"]], "rule_version": item.get("rule_version") if VERSION.fullmatch(str(item.get("rule_version", ""))) else "0.0.0",
            "reason": f"Anonymized static metadata evidence {number:03d}; original content is not published.", "status": _enum(item.get("status"), STATUSES, "unknown")}
        if item.get("object_path") is not None:
            record["object_path"] = f"/object_{number:03d}"
        eid = stable_id("evidence", record)
        evidence_ids[item["id"]] = eid
        evidence.append({"id": eid, **record, "collected_at": _stamp(item.get("collected_at"))})
    def proof(obj):
        return sorted({evidence_ids[eid] for eid in obj.get("evidence", []) if eid in evidence_ids})
    caps = _caps()
    techs = {c["technology"] for c in caps}
    nodes = []
    for original in raw.get("nodes", []):
        attrs = {"definition_only": True, "runtime_state": "unknown"}
        if isinstance(original.get("attributes", {}).get("entrypoint"), bool): attrs["entrypoint"] = original["attributes"]["entrypoint"]
        resource = original.get("attributes", {}).get("resource_type")
        if resource in RESOURCES: attrs["resource_type"] = resource
        dataset = original.get("attributes", {}).get("dataset")
        if dataset in node_ids: attrs["dataset"] = node_ids[dataset]
        technology = _enum(original.get("technology"), techs, "unidentified")
        name = node_names[original["id"]]
        nodes.append({"id": node_ids[original["id"]], "kind": original["kind"], "name": name,
            "environment": env_map[original["environment"]], "namespace": namespaces[original["namespace"]],
            "technology": technology, "status": _enum(original.get("status"), STATUSES, "unknown"), "attributes": attrs,
            "rule_concepts": ["anonymized_static_definition"], "evidence": proof(original),
            "explanation": f"{name} is an anonymized declared {original['kind']}; original names and content are withheld."})
    edge_records = {}
    for original in raw.get("edges", []):
        if original.get("kind") not in EDGE_KINDS or original["source"] not in node_ids or original["target"] not in node_ids: continue
        attrs = {"runtime_verified": False}
        before = original.get("attributes", {})
        if before.get("via") in node_ids: attrs["via"] = node_ids[before["via"]]
        if before.get("condition") in CONDITIONS: attrs["condition"] = before["condition"]
        if before.get("relation") in RELATIONS: attrs["relation"] = before["relation"]
        src, dst = node_ids[original["source"]], node_ids[original["target"]]
        eid = stable_id("edge", src, dst, original["kind"], attrs)
        record = {"id": eid, "source": src, "target": dst, "kind": original["kind"],
            "status": _enum(original.get("status"), STATUSES, "unknown"), "attributes": attrs, "evidence": proof(original)}
        if eid in edge_records:
            record["evidence"] = sorted(set(record["evidence"] + edge_records[eid]["evidence"]))
        edge_records[eid] = record
    edges = list(edge_records.values())
    detections = []
    for item in raw.get("detections", []):
        if item.get("artifact_id") not in artifact_ids: continue
        technology = _enum(item.get("technology"), techs, "unidentified")
        category = _enum(item.get("category"), CATEGORIES, "ambiguous")
        detections.append({"technology": technology, "family": next((c["family"] for c in caps if c["technology"] == technology), "unidentified"),
            "artifact_id": artifact_ids[item["artifact_id"]], "source_id": source_map[item["source_id"]], "environment": env_map[item["environment"]],
            "category": category, "confidence": _enum(item.get("confidence"), {"high", "medium", "low"}, "low"),
            "versions": [str(v) for v in item.get("versions", []) if VERSION.fullmatch(str(v))],
            "client_versions": [str(v) for v in item.get("client_versions", []) if VERSION.fullmatch(str(v))],
            "version_kinds": [v for v in item.get("version_kinds", []) if v in {"server", "client", "dependency", "tool", "unknown"}],
            "reasons": ["Technology evidence from an authorized static scan; identifiers anonymized."], "support": next((c["maturity"] for c in caps if c["technology"] == technology), "detection-only"),
            "selected": bool(item.get("selected")), "analysis_status": _enum(item.get("analysis_status"), {"analyzed_subset", "detection_only", "failed", "not_requested"}, "detection_only"), "conflicts": [], "evidence": proof(item)})
    issues = []
    for item in raw.get("issues", []):
        code = _enum(item.get("code"), SAFE_CODES, "unsupported_or_unrecognized")
        issues.append({"code": code, "message": _issue_text(code), "severity": _enum(item.get("severity"), {"info", "warning", "error"}, "warning"),
            "artifact_id": artifact_ids.get(item.get("artifact_id")), "evidence": proof(item)})
    result = {"schema_version": "1", "phase": "analyzed", "project": PROJECT, "collected_at": _stamp(raw.get("collected_at")),
        "registry_fingerprint": _hash(raw.get("registry_fingerprint"), 64), "effective_config": deepcopy(CONFIG),
        "sources": [{"id": source_map[s["id"]], "kind": "directory", "environment": env_map[s["environment"]], "service": namespaces[s.get("service", s["id"])], "path": "withheld"} for s in raw.get("sources", [])],
        "artifacts": artifacts, "nodes": sorted(nodes,key=lambda n:n["id"]), "edges": sorted(edges,key=lambda e:e["id"]), "evidence": sorted(evidence,key=lambda e:e["id"]),
        "detections": detections, "issues": issues, "references": [], "links": [], "annotations": [], "capabilities": caps,
        "metrics": {key: value for key, value in raw.get("metrics", {}).items() if key in {"files", "input_bytes", "adapter_runs", "adapter_failures", "elapsed_seconds"} and isinstance(value,(int,float)) and not isinstance(value,bool)},
        "publication": {"profile": PROFILE, "policy": POLICY, "identifiers_anonymized": True, "source_code_included": False, "business_rows_included": False,
            "evidence_locations": NOTICE, "source_snapshot_id": _hash(raw.get("snapshot_id"),24)}}
    result["architecture"] = recover(result)
    result["snapshot_id"] = digest(result)[:24]
    mapping = {"sources": source_map, "environments": env_map, "namespaces": namespaces, "node_names": node_names,
        "node_ids": node_ids, "artifact_ids": artifact_ids, "artifact_paths": artifact_paths, "evidence_ids": evidence_ids,
        "original_node_names": {node_ids[node["id"]]: node["name"] for node in raw.get("nodes", [])},
        "original_artifact_paths": {artifact_ids[item["id"]]: {"source_id": item["source_id"], "path": item["path"]} for item in raw.get("artifacts", [])},
        "notice": "PRIVATE reverse mapping; never publish this file."}
    validate_public_snapshot(result)
    return result, mapping


def _validate_public_snapshot(value):
    """Reject arbitrary free text even if an attacker updates a bundle digest."""
    expected = {"schema_version","phase","project","collected_at","registry_fingerprint","effective_config","sources","artifacts","nodes","edges","evidence","detections","issues","references","links","annotations","capabilities","metrics","publication","architecture","snapshot_id"}
    if not isinstance(value,dict) or set(value)!=expected or value["project"]!=PROJECT or value["schema_version"]!="1" or value["phase"]!="analyzed": raise ValueError("invalid public snapshot contract")
    marker={"profile":PROFILE,"policy":POLICY,"identifiers_anonymized":True,"source_code_included":False,"business_rows_included":False,"evidence_locations":NOTICE,"source_snapshot_id":value["publication"].get("source_snapshot_id")}
    if value["publication"]!=marker or not re.fullmatch(r"[a-f0-9]{24}",str(marker["source_snapshot_id"])): raise ValueError("invalid public projection marker")
    if value["effective_config"]!=CONFIG or value["capabilities"]!=_caps() or any(value[key] for key in ("references","links","annotations")): raise ValueError("private configuration or annotations prohibited")
    def keys(obj, expected):
        if not isinstance(obj,dict) or set(obj)!=set(expected):raise ValueError("public record has nonallowlisted fields")
    def alias(s,prefix):
        if not isinstance(s,str) or not re.fullmatch(prefix+r"_[0-9]{3,}",s):raise ValueError("private identifier not anonymized")
    def opaque(s,prefix,length=24):
        if not isinstance(s,str) or not re.fullmatch(re.escape(prefix)+r":[a-f0-9]{"+str(length)+r"}",s):raise ValueError("invalid public opaque identity")
    eids={e['id'] for e in value['evidence']}; nids={n['id'] for n in value['nodes']}; aids={a['id'] for a in value['artifacts']}
    for collection in ('evidence','nodes','artifacts','edges'):
        if len({item['id']for item in value[collection]})!=len(value[collection]):raise ValueError('duplicate public identity')
    def proof(obj, required=True):
        if not isinstance(obj['evidence'],list) or required and not obj['evidence'] or not set(obj['evidence'])<=eids:raise ValueError("public provenance unresolved")
    techs={c['technology'] for c in value['capabilities']}|{'unidentified'}
    for source in value['sources']:
        keys(source,['id','kind','environment','service','path']);alias(source['id'],'scope');alias(source['environment'],'environment');alias(source['service'],'namespace')
        if source['kind']!='directory' or source['path']!='withheld':raise ValueError('private source path prohibited')
    for a in value['artifacts']:
        keys(a,['id','source_id','environment','service','path','format','size','hash','inspection']);opaque(a['id'],'artifact');alias(a['source_id'],'scope');alias(a['environment'],'environment');alias(a['service'],'namespace')
        if a['format'] not in FORMATS or not re.fullmatch(r'artifact_[0-9]{3,}\.'+re.escape(a['format']),a['path']):raise ValueError('private artifact path prohibited')
        if not isinstance(a['size'],int) or a['size']<0 or a['hash'] is not None and not re.fullmatch(r'[a-f0-9]{64}',a['hash']) or a['inspection'] not in {'metadata-only','static-definition','unreadable'}:raise ValueError('invalid public artifact')
    for e in value['evidence']:
        keys(e,{'id','artifact_id','location','source_hash','adapter','adapter_version','rule_id','rule_version','reason','status','collected_at'}|({'object_path'} if 'object_path'in e else set()));opaque(e['id'],'evidence')
        opaque(e['artifact_id'],'artifact' if e['artifact_id'] in aids else 'scope-evidence')
        if e['adapter'] not in ADAPTERS or not re.fullmatch(r'Anonymized static metadata evidence [0-9]{3,}; original content is not published\.',e['reason']) or e['status'] not in STATUSES:raise ValueError('private evidence text prohibited')
        if not re.fullmatch(r'(?:scope_[0-9]{3,}/artifact_[0-9]{3,}\.[a-z]+|configured-scope/\[metadata\]):L[0-9]+',e['location']):raise ValueError('private evidence location prohibited')
        alias(e['rule_id'],'rule')
        if not VERSION.fullmatch(e['adapter_version']) or not VERSION.fullmatch(e['rule_version']) or not STAMP.fullmatch(e['collected_at']):raise ValueError('invalid evidence version/time')
        if e['source_hash'] is not None and not re.fullmatch(r'[a-f0-9]{64}',e['source_hash']):raise ValueError('invalid source hash')
        if 'object_path'in e and not re.fullmatch(r'/object_[0-9]{3,}',e['object_path']):raise ValueError('private source pointer prohibited')
    for n in value['nodes']:
        keys(n,['id','kind','name','environment','namespace','technology','status','attributes','rule_concepts','evidence','explanation'])
        if n['kind'] not in NODE_KINDS or n['kind']=='run':raise ValueError('runtime nodes prohibited in static profile')
        opaque(n['id'],n['kind']);alias(n['name'],n['kind']);alias(n['environment'],'environment');alias(n['namespace'],'namespace');proof(n)
        if n['technology'] not in techs or n['status'] not in STATUSES or n['rule_concepts']!=['anonymized_static_definition'] or n['explanation']!=f"{n['name']} is an anonymized declared {n['kind']}; original names and content are withheld.":raise ValueError('private node text prohibited')
        attrs=n['attributes']
        if not isinstance(attrs,dict) or set(attrs)-{'definition_only','runtime_state','entrypoint','resource_type','dataset'} or attrs.get('definition_only')is not True or attrs.get('runtime_state')!='unknown':raise ValueError('private node attributes prohibited')
        if 'entrypoint'in attrs and not isinstance(attrs['entrypoint'],bool) or 'resource_type'in attrs and attrs['resource_type']not in RESOURCES or 'dataset'in attrs and attrs['dataset']not in nids:raise ValueError('invalid public node metadata')
    for e in value['edges']:
        keys(e,['id','source','target','kind','status','attributes','evidence']);opaque(e['id'],'edge');proof(e)
        if e['kind']not in EDGE_KINDS or e['status']not in STATUSES or e['source']not in nids or e['target']not in nids:raise ValueError('invalid public edge')
        attrs=e['attributes']
        if not isinstance(attrs,dict) or set(attrs)-{'runtime_verified','via','condition','relation'} or attrs.get('runtime_verified')is not False or 'via'in attrs and attrs['via']not in nids or 'condition'in attrs and attrs['condition']not in CONDITIONS or 'relation'in attrs and attrs['relation']not in RELATIONS:raise ValueError('private edge attributes prohibited')
    for d in value['detections']:
        keys(d,['technology','family','artifact_id','source_id','environment','category','confidence','versions','client_versions','version_kinds','reasons','support','selected','analysis_status','conflicts','evidence']);proof(d);alias(d['source_id'],'scope');alias(d['environment'],'environment')
        family=next((c['family']for c in value['capabilities']if c['technology']==d['technology']),'unidentified')
        if d['technology']not in techs or d['family']!=family or d['artifact_id']not in aids or d['category']not in CATEGORIES or d['confidence']not in {'high','medium','low'} or d['reasons']!=['Technology evidence from an authorized static scan; identifiers anonymized.'] or d['conflicts'] or d['analysis_status']not in {'analyzed_subset','detection_only','failed','not_requested'} or d['support']not in {'reference','detection-only','experimental'} or not isinstance(d['selected'],bool):raise ValueError('private detection text prohibited')
        if any(not VERSION.fullmatch(v) for v in d['versions']+d['client_versions']) or any(v not in {'server','client','dependency','tool','unknown'}for v in d['version_kinds']):raise ValueError('invalid public version')
    for i in value['issues']:
        keys(i,['code','message','severity','artifact_id','evidence']);proof(i,required=False)
        if i['code']not in SAFE_CODES or i['message']!=_issue_text(i['code']) or i['severity']not in {'info','warning','error'} or i['artifact_id']is not None and i['artifact_id']not in aids:raise ValueError('private issue text prohibited')
    if set(value['metrics'])-{'files','input_bytes','adapter_runs','adapter_failures','elapsed_seconds'} or any(not isinstance(n,(int,float)) or isinstance(n,bool) or not math.isfinite(n) or n<0 for n in value['metrics'].values()):raise ValueError('private metric text prohibited')
    if not STAMP.fullmatch(value['collected_at']) or not re.fullmatch(r'[a-f0-9]{64}',value['registry_fingerprint']):raise ValueError('invalid public collection identity')
    base={k:v for k,v in value.items()if k not in {'architecture','snapshot_id'}}
    if value['architecture']!=recover(base):raise ValueError('public derived text does not match validated graph')
    if value['snapshot_id']!=digest({**base,'architecture':value['architecture']})[:24]:raise ValueError('public snapshot digest mismatch')


def validate_public_snapshot(value):
    """Validate closed fields and normalize all malformed-data failures."""
    try:
        _validate_public_snapshot(value)
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError, RecursionError):
        raise ValueError("malformed public projection") from None


def create_publication_manifest(snapshot_path):
    path=Path(snapshot_path)
    validate_public_snapshot(safe_json(path,100_000_000))
    return {'schema_version':'1','profile':PROFILE,'policy':POLICY,'snapshot_file':'snapshot.json','sha256':digest(path.read_bytes()),'source_code_included':False,'business_rows_included':False}


def verify_publication_bundle(snapshot_path, manifest_path):
    snapshot_path,manifest_path=Path(snapshot_path),Path(manifest_path)
    if snapshot_path.is_symlink() or manifest_path.is_symlink():raise ValueError('publication bundle must not use symlinks')
    if snapshot_path.stat().st_size > 20_000_000:raise ValueError('public snapshot exceeds size budget')
    manifest=safe_json(manifest_path)
    expected={'schema_version':'1','profile':PROFILE,'policy':POLICY,'snapshot_file':'snapshot.json','sha256':digest(snapshot_path.read_bytes()),'source_code_included':False,'business_rows_included':False}
    if manifest!=expected:raise ValueError('publication manifest/digest mismatch')
    snapshot=safe_json(snapshot_path,100_000_000)
    validate_public_snapshot(snapshot)
    return snapshot
