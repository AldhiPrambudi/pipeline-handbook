"""Private scans cannot become public by merely adding a marker or digest."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from pipeline_handbook.architecture import recover
from pipeline_handbook.publication import anonymize_snapshot, validate_public_snapshot, create_publication_manifest, verify_publication_bundle
from pipeline_handbook.security import digest
from tests.test_adapters import context


CANARY = "PRIVATE_ACCOUNT_OWNER_17382"


def private_snapshot():
    artifact,ctx=context("private source text " + CANARY, CANARY+".sql", "postgresql")
    artifact['size']=len(artifact['text'])
    pipeline=ctx.node('pipeline',CANARY,{'entrypoint':True,'sql':CANARY,'owner':CANARY,'inspection_points':[{'kind':'logs','location':'https://private.invalid/'+CANARY}]})
    source,target=ctx.dataset('raw.'+CANARY),ctx.dataset('final.'+CANARY)
    ctx.edge(source,target,'data_flow',{'via':pipeline,'private_connection':CANARY})
    ctx.issue('unsupported_sql','raw private message '+CANARY)
    result=ctx.result()
    raw={'schema_version':'1','phase':'analyzed','project':CANARY,'snapshot_id':'a'*24,'registry_fingerprint':'b'*64,'collected_at':'2026-10-30T00:00:00Z',
         'sources':[{'id':'fixture_dev','kind':'directory','environment':'dev','service':'orders','path':'/private/'+CANARY}],
         'artifacts':[{k:v for k,v in artifact.items()if k!='text'}], 'detections':[{'technology':'postgresql','family':'database','artifact_id':artifact['id'],'source_id':'fixture_dev','environment':'dev','category':'declared','confidence':'high','versions':['16.4','1-'+CANARY],'client_versions':[],'version_kinds':['server'],'reasons':[CANARY],'support':'reference','selected':True,'analysis_status':'analyzed_subset','evidence':[next(iter(ctx.evidences))]}],
         **result,'annotations':[{'node_id':pipeline,'owner':CANARY,'purpose':CANARY}], 'effective_config':{'source':CANARY,'credential':CANARY},'capabilities':[], 'metrics':{'files':1,'private_metadata':CANARY}}
    raw['architecture']=recover(raw)
    return raw


class PublicProjectionTests(unittest.TestCase):
    def test_alias_projection_removes_all_private_text_and_preserves_graph(self):
        raw=private_snapshot(); original=deepcopy(raw)
        public,mapping=anonymize_snapshot(raw)
        serialized=json.dumps(public)
        self.assertNotIn(CANARY,serialized)
        self.assertNotIn('private.invalid',serialized)
        self.assertNotIn('/private/',serialized)
        self.assertFalse(public['annotations'])
        self.assertEqual(len(raw['nodes']),len(public['nodes']))
        self.assertEqual(len(raw['edges']),len(public['edges']))
        self.assertEqual(raw,original)
        self.assertIn(CANARY,json.dumps(mapping))
        self.assertEqual(public['detections'][0]['versions'],['16.4'])
        self.assertEqual(len(public['evidence']),len({e['id']for e in public['evidence']}))
        validate_public_snapshot(public)

    def test_marker_or_updated_digest_cannot_authorize_private_fields(self):
        public,_=anonymize_snapshot(private_snapshot())
        mutations=[lambda p:p['nodes'][0]['attributes'].update(owner=CANARY),lambda p:p['annotations'].append({'owner':CANARY}),lambda p:p['evidence'][0].update(location=CANARY),lambda p:p['issues'][0].update(message=CANARY),lambda p:p['architecture']['findings'][0].update(text=CANARY),lambda p:p['metrics'].update(path=CANARY)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed=deepcopy(public);mutate(changed)
                changed['snapshot_id']=digest({k:v for k,v in changed.items()if k!='snapshot_id'})[:24]
                with self.assertRaises(ValueError):validate_public_snapshot(changed)

    def test_manifest_verifies_exact_bytes_and_refuses_links(self):
        public,_=anonymize_snapshot(private_snapshot())
        with tempfile.TemporaryDirectory()as name:
            folder=Path(name);snapshot=folder/'snapshot.json';manifest=folder/'manifest.json'
            snapshot.write_text(json.dumps(public,indent=2)+'\n')
            manifest.write_text(json.dumps(create_publication_manifest(snapshot)))
            self.assertEqual(verify_publication_bundle(snapshot,manifest),public)
            snapshot.write_text(snapshot.read_text()+' ')
            with self.assertRaises(ValueError):verify_publication_bundle(snapshot,manifest)
            linked=folder/'linked.json';linked.symlink_to(snapshot)
            with self.assertRaises(ValueError):verify_publication_bundle(linked,manifest)

    def test_runtime_observations_are_not_recast_as_static_facts(self):
        raw=private_snapshot();raw['nodes'][0]['status']='observed'
        with self.assertRaises(ValueError):anonymize_snapshot(raw)

    def test_lost_provenance_and_duplicate_identities_fail_closed(self):
        public,_=anonymize_snapshot(private_snapshot())
        for mutate in [lambda p:p['nodes'][0].update(evidence=[]),lambda p:p['nodes'].append(deepcopy(p['nodes'][0]))]:
            changed=deepcopy(public);mutate(changed)
            with self.assertRaises(ValueError):validate_public_snapshot(changed)

    def test_private_text_cannot_hide_in_evidence_identity_with_fresh_digest(self):
        public,_=anonymize_snapshot(private_snapshot())
        public['evidence'][0]['artifact_id']=CANARY
        base={k:v for k,v in public.items()if k not in {'architecture','snapshot_id'}}
        public['architecture']=recover(base)
        public['snapshot_id']=digest({k:v for k,v in public.items()if k!='snapshot_id'})[:24]
        with self.assertRaises(ValueError):validate_public_snapshot(public)
