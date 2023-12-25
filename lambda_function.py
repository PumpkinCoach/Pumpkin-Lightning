import json
import logging
import openai
import time
import os
import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.conditions import Attr
from slack_bolt import App
from slack_bolt.adapter.aws_lambda import SlackRequestHandler
# from slack_bolt.adapter.aws_lambda.lambda_s3_oauth_flow import LambdaS3OAuthFlow

app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    process_before_response=True,
    # oauth_flow=LambdaS3OAuthFlow()
)

handler = SlackRequestHandler(app)
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('inha-pumpkin-coach')
api_key = '' # use your openai-api-key

SlackRequestHandler.clear_all_log_handlers()
logging.basicConfig(format="%(asctime)s %(message)s", level=logging.DEBUG)


# @app.event("im_created")
# def initialize(message, say):
#     say(f"Hello, <@{message['user']}>")

def respond_to_slack_within_3_seconds(ack):
    ack()


def chatgpt_response(message, say):
    
    # OpenAI API 키를 설정합니다
    openai.api_key = api_key
    
    # OpenAI GPT-3를 사용하여 텍스트를 생성합니다
    response = openai.Completion.create(
        engine='text-davinci-003',
        prompt=message['text'][5:],
        temperature=0.5,
        max_tokens=1024,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0
    )
    
    say("답변: " + str(response['choices'][0]['text']))

app.message("!GPT")(
    ack=respond_to_slack_within_3_seconds,
    lazy=[chatgpt_response]
)

#초기 유저 설정
@app.message("!등록")
def set_user(message, say):
    team_id=message['team']
    user_id=message['user']
    response=table.put_item(Item={'PK': f'lightning#{team_id}', 'SK': f'user#{user_id}', 'user_id': user_id, 'match_id': '', 'wait': False})
    say("등록이 완료되었습니다.")
    
@app.message("!도움")
def help(say):
    say(
        {
        	"blocks": [
        		{
        			"type": "header",
        			"text": {
        				"type": "plain_text",
        				"text": ":jack_o_lantern: Pumpkin-Lightning :zap: 도움말"
        			}
        		},
        		{
        			"type": "divider"
        		},
        		{
        			"type": "context",
        			"elements": [
        				{
        					"type": "mrkdwn",
        					"text": "*!등록* 번개채팅을 시작하기 위해 사용자를 등록합니다.\n*!매칭* 현재 대화할 수 있는 상대를 찾습니다.\n*!종료* 현재 대화중인 상대가 있다면 대화를 종료합니다.\n*!GPT (스크립트)* GPT에게 질문합니다\n*!도움* Pumpkin-Lightning의 도움말을 보여줍니다.\n"
        				}
        			]
        		},
        		{
        			"type": "section",
        			"text": {
        				"type": "mrkdwn",
        				"text": "‼처음 사용하는 유저는 *!등록* 을 통해서 꼭 유저 정보를 등록해주시길 바랍니다.‼"
        			}
        		}
        	]
        }
    )

#다른 유저와 매칭
@app.message("!매칭")
def match(message, respond, say):
    team_id=message['team']
    user_id=message['user']
    match_id=get_match_id(team_id, user_id)
    
    if match_id != '':
        say("이미 대화 중인 상대가 있습니다!")
        return
    say(
        {
        	"blocks": [
        		{
        			"type": "divider"
        		},
        		{
        			"type": "section",
        			"text": {
        				"type": "mrkdwn",
        				"text": ":new: *지금 바로 대화 상대를 찾아볼까요?*"
        			}
        		},
        		{
        			"type": "actions",
        			"elements": [
        				{
        					"type": "button",
        					"text": {
        						"type": "plain_text",
        						"text": "예"
        					},
        					"style": "primary",
        					"value": "match_yes",
        					"action_id": "match_yes"
        				},
        				{
        					"type": "button",
        					"text": {
        						"type": "plain_text",
        						"text": "아니오"
        					},
        					"style": "danger",
        					"value": "match_no",
        					"action_id": "match_no"
        				}
        			]
        		}
        	]
        }
    )

def run_long_process(body, respond, say):
    team_id=body['team']['id']
    user_id=body['user']['id']
    flag=check_wait(team_id, user_id) # 이미 매칭중인지 확인
    if flag is True:
        respond("이미 매칭중입니다!")
    else:    
        respond("매칭중입니다...")
        PK=f"lightning#{team_id}"
        SK=f"user#{user_id}"
        response=table.query(KeyConditionExpression=Key('PK').eq(PK), FilterExpression= Attr('wait').eq(True))
        if response['Count'] != 0:  # 현재 매칭 중인 상대가 있을 때
            match_id=response['Items'][0]['user_id']
            response=table.put_item(Item={'PK': PK, 'SK': f'user#{user_id}', 'user_id': user_id, 'match_id': match_id, 'wait': False})  # 매칭 관계 형성
            response=table.put_item(Item={'PK': PK, 'SK': f'user#{match_id}', 'user_id': match_id, 'match_id': user_id, 'wait': False})
            say(text="매칭에 성공했습니다!",channel=user_id)
            say(text="매칭에 성공했습니다!",channel=match_id)
        else:   # 현재 매칭 중인 상대가 없을 때
            if body['actions'][0]['value'] == "alarm_yes":
                respond("매칭에 실패했습니다. !매칭을 통해 새로운 대화 상대를 찾아보세요!")
                return
            # 알람!!
            response=table.put_item(Item={'PK': PK, 'SK': SK, 'user_id': user_id, 'match_id': '', 'wait': True})
            response=table.query(KeyConditionExpression=Key('PK').eq(PK), FilterExpression=Attr('wait').eq(False) & Attr('match_id').eq(''))
            blocks=[
            		{
            			"type": "divider"
            		},
            		{
            			"type": "section",
            			"text": {
            				"type": "mrkdwn",
            				"text": ":zap:*지금 대화 상대를 찾고있는 유저가 있습니다! 매칭 하시겠습니까?*"
            			}
            		},
            		{
            			"type": "actions",
            			"elements": [
            				{
            					"type": "button",
            					"text": {
            						"type": "plain_text",
            						"text": "예"
            					},
            					"style": "primary",
            					"value": "alarm_yes",
            					"action_id": "match_yes"
            				},
            				{
            					"type": "button",
            					"text": {
            						"type": "plain_text",
            						"text": "아니오"
            					},
            					"style": "danger",
            					"value": "alarm_no",
            					"action_id": "match_no"
            				}
            			]
            		}
            	]
            for i in range(response['Count']):
                say(blocks=blocks, channel=response['Items'][i]['user_id'])
            time.sleep(60) # 대기시간 설정
            flag=check_wait(team_id, user_id) # 아직 매칭이 안되었다면 남아있음
            if flag is True:  # 매칭에 실패했을 때
                response=table.put_item(Item={'PK':PK, 'SK':SK, 'user_id': user_id, 'match_id': '', 'wait': False})
                respond("매칭 실패")
            else:
                return

def check_wait(team_id, user_id):
    PK=f"lightning#{team_id}"
    SK=f"user#{user_id}"
    response=table.query(KeyConditionExpression=Key('PK').eq(PK) & Key('SK').eq(SK), FilterExpression= Attr('wait').eq(True))
    return response['Count'] != 0

#매칭 커맨드에서 예 버튼을 눌렀을 때
app.action("match_yes")(
    ack=respond_to_slack_within_3_seconds,
    lazy=[run_long_process]  
)

#매칭 커맨드에서 아니오 버튼을 눌렀을 때
@app.action("match_no")
def match_no(ack, respond):
    ack()
    respond("매칭을 취소합니다.")

#상대방과의 대화를 종료
@app.message("!종료")
def close_connection(message, say):
    team_id=message['team']
    user_id=message['user']
    match_id=get_match_id(team_id, user_id) # 유저와 현재 매칭된 id 구하는 함수,
    
    if match_id == '':
        say("현재 대화 중인 상대가 없습니다. !매칭을 이용해서 새로운 대화 상대를 찾아보세요!")
    else:
        PK=f'lightning#{team_id}'
        response=table.put_item(Item={'PK':PK, 'SK': f'user#{user_id}', 'user_id': user_id, 'match_id': '', 'wait': False})
        response=table.put_item(Item={'PK':PK, 'SK': f'user#{match_id}', 'user_id': match_id, 'match_id': '', 'wait': False})
        say(text="상대방과의 대화가 종료되었습니다.",channel=user_id)
        say(text="상대방과의 대화가 종료되었습니다.",channel=match_id)
    
#채팅
@app.message()
def send_message(message, say):
    team_id=message['team']
    user_id=message['user']
    match_id=get_match_id(team_id, user_id)
    
    #매칭된 상대가 없을 때
    if match_id == '':
        say("현재 대화 중인 상대가 없습니다. !매칭을 이용해서 새로운 대화 상대를 찾아보세요!")
    else:
        say(text=message['text'], channel=match_id)
        
#user_id를 통해 매칭되어 있는 상대의 id를 반환
def get_match_id(team_id, user_id):
    PK=f"lightning#{team_id}"
    SK=f"user#{user_id}"
    response=table.query(KeyConditionExpression=Key('PK').eq(PK) & Key('SK').eq(SK))
    
    return response['Items'][0]['match_id']

def lambda_handler(event, context):
	return handler.handle(event, context)
