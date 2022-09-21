import copy

import boto3

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

    def __init__(self, client) -> None:
        self.client = client

    @classmethod
    def new(cls, *args, **kwargs):
        client = get_mturk_client(*args, **kwargs)
        return cls(client)

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

    def create_HIT(self, external_url):
        raise NotImplementedError()
