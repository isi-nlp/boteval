import copy
from dataclasses import dataclass
import boto3
import json

from . import C, log


def get_mturk_client(sandbox=False, endpoint_url=C.MTURK_SANDBOX, profile=None, **props):

    params = copy.deepcopy(props)
    if sandbox:
        params["endpoint_url"] = endpoint_url
    if profile:
        boto3.setup_default_session(profile_name=profile)
    log.info(f'creating mturk with {params}')
    return boto3.client('mturk', **params)



class MTurkService:

    def __init__(self, client, hit_settings=None) -> None:
        self.name = C.MTURK
        self.client = client
        self.hit_settings = hit_settings
        self.is_sandbox = self.endpoint_url == C.MTURK_SANDBOX

    @classmethod
    def new(cls, client, hit_settings):
        client = get_mturk_client(**client)
        return cls(client, hit_settings=hit_settings)

    @property
    def endpoint_url(self) -> str:
        return self.client.meta.endpoint_url

    def get_assignment(self, assignment_id):
        return self.client.get_assignment(AssignmentId=assignment_id)['Assignment']

    def list_qualification_types(self, max_results=C.AWS_MAX_RESULTS, query: str=''):
        data = self.client.list_qualification_types(
            MustBeRequestable=True, MustBeOwnedByCaller=True,
            MaxResults=max_results)
        qtypes = data['QualificationTypes']
        if query:
            query = query.lower()
            qtypes = [qt for qt in qtypes
                    if query in qt['Name'].lower() or query in qt['Description']]
        return qtypes

    def list_HITS(self, qual_id:str, max_results=C.AWS_MAX_RESULTS):
        return self.client.list_hits_for_qualification_type(
            QualificationTypeId=qual_id,
            MaxResults=max_results)

    def list_workers_for_qualtype(self, qual_id:str, max_results=C.AWS_MAX_RESULTS):
        return self.client.list_workers_with_qualification_type(
            QualificationTypeId=qual_id,
            MaxResults=max_results)

    def list_all_hits(self, max_results=C.AWS_MAX_RESULTS, next_token=None):
        args = dict(MaxResults=max_results)
        if next_token:
            args['NextToken'] = next_token
        return self.client.list_hits(**args)

    def list_assignments(self, HIT_id: str, max_results=C.AWS_MAX_RESULTS):
        return self.client.list_assignments_for_hit(
            HITId=HIT_id, MaxResults=max_results)

    def qualify_worker(self, worker_id: str, qual_id: str, send_email=True):
        log.info(f"Qualifying worker: {worker_id} for {qual_id}")
        return self.client.associate_qualification_with_worker(
            QualificationTypeId=qual_id,
            WorkerId=worker_id,
            IntegerValue=1,
            SendNotification=send_email
            )

    def disqualify_worker(self, worker_id: str, qual_id: str, reason: str=None):
        log.info(f"Disqualifying worker: {worker_id} for {qual_id}")
        return self.client.disassociate_qualification_from_worker(
            QualificationTypeId=qual_id,
            WorkerId=worker_id,
            Reason=reason
            )

    def create_HIT(self, external_url, max_assignments, reward, description, title=None, frame_height=640, **kwargs):
        if not external_url.startswith('https://'):
            raise Exception(f"MTurk requires HTTPS URL")

        namespace = 'http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd'
        question_data = f'''<?xml version="1.0" encoding="UTF-8"?>
            <ExternalQuestion xmlns="{namespace}">
            <ExternalURL>{external_url}</ExternalURL>
            <FrameHeight>{frame_height}</FrameHeight>
            </ExternalQuestion>'''
        args = {}
        if self.hit_settings:
            args |= copy.deepcopy(self.hit_settings)
        args |= kwargs
        args |= dict(
            Question=question_data,
            MaxAssignments=max_assignments,
            Reward=reward
        )
        if title:
            if 'Title' in args:
                title += '\n' + args['Title']
            args['Title'] = title

        if description:
            if 'Description' in args:
                description += '\n' + args['Description']
            args['Description'] = description

        log.info(f'creating HIT..')
        response = self.client.create_hit(**args)['HIT']
        hit_id = response['HITId']
        hit_group_id = response['HITGroupId']
        subdomain = 'workersandbox' if self.is_sandbox else 'www'
        task_url = f'https://{subdomain}.mturk.com/projects/{hit_group_id}/tasks'
        log.info(f'HIT created: {hit_id}  {task_url}')
        
        log.info(f'Task URL: {task_url}')
        return hit_id, task_url, response
