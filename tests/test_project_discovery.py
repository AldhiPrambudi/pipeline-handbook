"""Detection improvements justified by the NCBS source-only compatibility test."""
import json
import unittest
from pipeline_handbook.detection import detect
from pipeline_handbook.security import safe_json
from pipeline_handbook.config import DATA


def discoveries(text,fmt='json'):
    artifact={'id':'a','source_id':'scope','environment':'repository','service':'service','format':fmt,'text':text}
    return detect(artifact,safe_json(DATA/'builtin.json')['entries'])


class ProjectDiscoveryTests(unittest.TestCase):
    def test_base_image_tag_is_not_a_docker_engine_version(self):
        found=discoveries('FROM python:3.12-slim\n','dockerfile')
        docker=next(d for d in found if d['technology']=='docker')
        self.assertEqual(docker['versions'],[])

    def test_compose_images_declare_products_without_runtime_proof(self):
        text=json.dumps({'name':'example','services':{'db':{'image':'postgres:16'},'store':{'image':'chrislusf/seaweedfs:4.47'},'bi':{'image':'metabase/metabase@sha256:'+'a'*64}},'networks':{}})
        found={d['technology']:d for d in discoveries(text)}
        self.assertTrue({'postgresql','seaweedfs','metabase'}<=found.keys())
        self.assertEqual(found['postgresql']['versions'],['16'])
        self.assertEqual(found['seaweedfs']['versions'],['4.47'])
        self.assertEqual(found['metabase']['versions'],[])
        self.assertTrue(all(found[t]['category']=='declared'for t in ('postgresql','seaweedfs','metabase')))

    def test_dynamic_image_reference_does_not_invent_a_version_or_product(self):
        text=json.dumps({'name':'example','services':{'db':{'image':'postgres:${VERSION}'}},'networks':{}})
        self.assertFalse(any(d['technology']=='postgresql'for d in discoveries(text)))

    def test_client_import_is_not_server_observation_and_dbt_filename_is_insufficient(self):
        pg=next(d for d in discoveries('import psycopg\n','py')if d['technology']=='postgresql')
        self.assertEqual(pg['versions'],[])
        self.assertEqual(pg['category'],'declared')
        self.assertFalse(any(d['technology']=='dbt'for d in discoveries('name: example\n','yml')))
        self.assertTrue(any(d['technology']=='dbt'and d['category']=='declared'for d in discoveries('name: example\nconfig-version: 2\nprofile: example\nmodel-paths: [models]\n','yml')))
