import copy
import logging

import boto3
import requests
from flask import request
import datetime

from . import C, log
from .utils import jsonify, render_template
from .model import ChatThread


logging.getLogger('boto3').setLevel(C.MTURK_LOG_LEVEL)
logging.getLogger('botocore').setLevel(C.MTURK_LOG_LEVEL)
logging.getLogger('nose').setLevel(C.MTURK_LOG_LEVEL)


def get_mturk_client(sandbox=False, endpoint_url=C.MTURK_SANDBOX_URL, profile=None, **props):

    params = copy.deepcopy(props)
    if sandbox:
        params["endpoint_url"] = endpoint_url
    if profile:
        boto3.setup_default_session(profile_name=profile)
    log.info(f'creating mturk with {params}')
    return boto3.client('mturk', **params)


class MTurkService:

    def __init__(self, client, hit_settings=None) -> None:
        self.client = client
        self.hit_settings = hit_settings
        self.is_sandbox = 'sandbox' in self.endpoint_url
        self.name =  C.MTURK_SANDBOX if self.is_sandbox else C.MTURK

    @classmethod
    def new(cls, client, hit_settings, **kwargs):
        client = get_mturk_client(**client)
        return cls(client, hit_settings=hit_settings)

    @property
    def endpoint_url(self) -> str:
        return self.client.meta.endpoint_url

    @property
    def external_submit_url(self, subhost=None)-> str:
        assert subhost in (None, 'live', 'sandbox', 'www', 'workersandbox')
        if subhost is None:
            subhost = self.is_sandbox and 'workersandbox' or 'www'
        elif subhost == 'sandbox':
            subhost = 'workersandbox'
        elif subhost == 'live':
            subhost = 'www'

        return f'https://{subhost}.mturk.com/mturk/externalSubmit'

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

    def get_qualification_type_id_by_name(self, qualification_name):
        data = self.client.list_qualification_types(
            MustBeRequestable=True, MustBeOwnedByCaller=True,
            MaxResults=C.AWS_MAX_RESULTS)

        qtypes = data['QualificationTypes']
        for cur_type in qtypes:
            if cur_type['Name'] == qualification_name:
                return cur_type['QualificationTypeId']

        return ''

    def is_worker_qualified(self, user_worker_id, qual_name):
        human_moderator_qual_id = self.get_qualification_type_id_by_name(
            qualification_name=qual_name)

        workers = self.list_workers_for_qualtype(qual_id=human_moderator_qual_id, max_results=C.AWS_MAX_RESULTS)

        qual_list_js = workers.get('Qualifications')
        for cur_qual in qual_list_js:
            if user_worker_id == cur_qual.get('WorkerId'):
                return True
        return False

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
            HITId=HIT_id,
            MaxResults=max_results,
            AssignmentStatuses=['Submitted', 'Approved', 'Rejected']
        )

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

    def create_HIT(self, external_url, max_assignments, reward, frame_height=800, **kwargs):
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
        
        # keeping title and description will group the HITs together

        log.info(f'creating HIT..')
        response = self.client.create_hit(**args)['HIT']
        hit_id = response['HITId']
        hit_group_id = response['HITGroupId']
        subdomain = 'workersandbox' if self.is_sandbox else 'worker'
        task_url = f'https://{subdomain}.mturk.com/projects/{hit_group_id}/tasks'
        log.info(f'HIT created: {hit_id}  {task_url}')
        
        log.info(f'Task URL: {task_url}')
        return hit_id, task_url, response

    def task_complete(self, thread: ChatThread, result):
        assert thread.ext_src == self.name
        assignment_id = thread.ext_id
        
        data = { str(key): str(val) for key, val in result.items()}
        data['assignmentId'] = thread.ext_id
        data['topicId'] = thread.topic_id
        data['threadId'] = thread.id
        url = self.external_submit_url + f'?assignmentId={thread.ext_id}'
        log.info(f'Marking Assignment {assignment_id} as complete; url={url}')
        headers = {'Content-Type': 'application/x-www-form-urlencoded',}
        reply = requests.post(url, data=data, headers=headers)
        log.info(f'reply : {reply}')
        return reply.status_code == 200


class MTurkController:

    def __init__(self, mturk: MTurkService, templates_dir='admin/mturk/'):
        """Registers mechanical turk controller

        Args:
            mturk (_type_): MTurk service object
            where (_type_): live or sandbox
        """
        #assert where in ('live', 'sandbox')
        #self.where = where
        self.mturk: MTurkService = mturk
        self.templates_dir = templates_dir
        self.meta = dict(mturk_endpoint_url=self.mturk.endpoint_url,
                         crowd_name=self.mturk.name)
        assert mturk.name in (C.MTURK, C.MTURK_SANDBOX)
        self.meta['mturk_where'] = {C.MTURK: 'live', C.MTURK_SANDBOX: 'sandbox'}[mturk.name]
        self.meta['crowd_name'] = mturk.name
    def register_routes(self, router, login_decorator=None):
        log.info(f'Registering mturk routes')
        rules = [
            ('/', self.home, dict(methods=["GET"])),
            ('/qualification/', self.list_qualifications, dict(methods=["GET"])),
            ('/qualification/<qual_id>', self.get_qualification, dict(methods=["GET"])),
            ('/qualification/<qual_id>', self.delete_qualification, dict(methods=['DELETE'])),
            ('/HIT/', self.list_HITs, dict(methods=["GET"])),
            ('/HIT/<HIT_id>', self.get_HIT, dict(methods=["GET"])),
            ('/HIT/<HIT_id>', self.delete_hit, dict(methods=['DELETE'])),
            ('/HIT/<HIT_id>/expire', self.expire_HIT, dict(methods=['DELETE'])),
            ('/assignment/<asgn_id>/approve', self.approve_assignment, dict(methods=["POST"])),
            ('/assignment/<asgn_id>/<worker_id>/<payment>/give_bonus', self.give_bonus, dict(methods=["POST"])),
            ('/worker/<worker_id>/qualification', self.qualify_worker, dict(methods=["POST", "PUT"])),
            ('/worker/<worker_id>/qualification', self.disqualify_worker, dict(methods=["DELETE"])),
        ]
        crowd_name = self.mturk.name
        for path, view_func, opts in rules:
            endpoint_name = crowd_name + '_' + view_func.__name__
            #log.info(f'Registering {endpoint_name}')
            if login_decorator:
                view_func = login_decorator(view_func)
            router.add_url_rule(f"/{crowd_name}/{path}", view_func=view_func, endpoint=endpoint_name, **opts)

    def render_template(self, name, *args, **kwargs):
        return render_template(self.templates_dir + name, *args, meta=self.meta, **kwargs)

    def home(self):
        return self.render_template('home.html')

    def list_qualifications(self):
        qtypes = self.mturk.list_qualification_types(max_results=C.AWS_MAX_RESULTS)
        return self.render_template('qualifications.html', qtypes=qtypes)

    def get_qualification(self, qual_id):
        HITs = self.mturk.list_HITS(qual_id=qual_id,max_results=C.AWS_MAX_RESULTS)
        workers = self.mturk.list_workers_for_qualtype(qual_id=qual_id, max_results=C.AWS_MAX_RESULTS)
        data = dict(HITs=HITs['HITs'], workers=workers['Qualifications'])
        return self.render_template('qualification.html', data=data, qual_id=qual_id)

    def delete_qualification(self, qual_id):
        data = self.mturk.mturk.delete_qualification_type(QualificationTypeId=qual_id)
        return jsonify(data), 200

    def list_HITs(self):
        data = self.mturk.list_all_hits()
        return self.render_template('HITs.html', data=data)

    def get_HIT(self, HIT_id):
        data = self.mturk.list_assignments(HIT_id=HIT_id, max_results=100)
        print(data)
        qtypes = None
        bonus_settings = self.mturk.hit_settings
        if not "Reward" in bonus_settings:
            return "You must set a reward attribute in the conf.yaml file."
        base_pay = float(bonus_settings["Reward"])
        pay_per_hour = float(bonus_settings.get("DesiredRate", 15))
        bonus_pay = []
        if data['Assignments']:
            qtypes = self.mturk.list_qualification_types(max_results=100)
            for i in enumerate(data['Assignments']):
                index = i[0]
                this_assignment = i[1]
                total_time = this_assignment['SubmitTime'] - this_assignment['AcceptTime']
                total_seconds = total_time.total_seconds()
                this_bonus = self.get_bonus(base_pay=base_pay, pay_per_hour=pay_per_hour, total_seconds=total_seconds)
                bonus_pay.insert(index, this_bonus)
        return self.render_template('HIT.html', data=data, HIT_id=HIT_id, qtypes=qtypes, base_pay=base_pay, pay_per_hour=pay_per_hour, bonus_pay=bonus_pay)

    def delete_hit(self, HIT_id):
        data = self.mturk.client.delete_hit(HITId=HIT_id)
        return jsonify(data), data.get('HTTPStatusCode', 200)

    def approve_assignment(self, asgn_id):
        #RequesterFeedback=feedback # any feed back message to worker
        data = self.mturk.client.approve_assignment(AssignmentId=asgn_id)
        return jsonify(data), data.get('HTTPStatusCode', 200)

    #Calculates bonus given to worker to ensure the worker works $15 per hour.
    def give_bonus(self, worker_id, payment, asgn_id):
        bonus_settings = self.mturk.hit_settings
        bonus_payment_ret = float(payment)
        bonus_reason = bonus_settings["BonusReason"]
        desired_rate = str(bonus_settings["DesiredRate"])
        bonus_reason = bonus_reason.replace("[RATE]", desired_rate)
        data = self.mturk.client.send_bonus(WorkerId=worker_id,BonusAmount=str(bonus_payment_ret),AssignmentId=asgn_id,Reason=bonus_reason)
        return jsonify(data), data.get('HTTPStatusCode', 200)
    
    def get_bonus(self, pay_per_hour, base_pay, total_seconds):
        bonus_payment = 0.00
        total_mins = ((1.00/60.0) * total_seconds)
        rate_payment = (pay_per_hour / 60.0) * total_mins
        if rate_payment > base_pay:
            bonus_payment = rate_payment - base_pay
        bonus_payment_ret = round(bonus_payment, 2)
        return bonus_payment_ret

    def qualify_worker(self, worker_id):
        qual_id = request.form.get('QualificationTypeId')
        log.info(f"Qualify: worker: {worker_id}  to qualification: {qual_id}")
        if not qual_id:
            return 'ERROR: QualificationTypeId argument is requires', 400
        data = self.mturk.qualify_worker(worker_id=worker_id, qual_id=qual_id)
        return jsonify(data), data.get('HTTPStatusCode', 200)

    def disqualify_worker(self, worker_id, qual_id):
        log.info(f"Disqualify: worker: {worker_id} from qualification: {qual_id}")
        reason = request.values.get('reason', '')
        data = self.mturk.disqualify_worker(worker_id=worker_id,qual_id=qual_id, reason=reason)
        return jsonify(data), data.get('HTTPStatusCode', 200)

    def expire_HIT(self, HIT_id):
        log.info(f"Expiring HIT: {HIT_id}")
        data = self.mturk.client.update_expiration_for_hit(
                HITId=HIT_id, ExpireAt=datetime.datetime(2021, 1, 1)
            )
        return jsonify(data), data.get('HTTPStatusCode', 200)
