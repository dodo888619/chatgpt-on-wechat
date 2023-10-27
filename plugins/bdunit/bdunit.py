# encoding:utf-8
import json
import os
import uuid
from uuid import getnode as get_mac

import requests

import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from plugins import *

"""利用百度UNIT实现智能对话
    如果命中意图，返回意图对应的回复，否则返回继续交付给下个插件处理
"""


@plugins.register(
    name="BDunit",
    desire_priority=0,
    hidden=True,
    desc="Baidu unit bot system",
    version="0.1",
    author="jackson",
)
class BDunit(Plugin):
    def __init__(self):
        super().__init__()
        try:
            conf = super().load_config()
            if not conf:
                raise Exception("config.json not found")
            self.service_id = conf["service_id"]
            self.api_key = conf["api_key"]
            self.secret_key = conf["secret_key"]
            self.access_token = self.get_token()
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            logger.info("[BDunit] inited")
        except Exception as e:
            logger.warn("[BDunit] init failed, ignore ")
            raise e

    def on_handle_context(self, e_context: EventContext):
        if e_context["context"].type != ContextType.TEXT:
            return

        content = e_context["context"].content
        logger.debug(f"[BDunit] on_handle_context. content: {content}")
        parsed = self.getUnit2(content)
        if intent := self.getIntent(parsed):
            logger.debug("[BDunit] Baidu_AI Intent= %s", intent)
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = self.getSay(parsed)
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
        else:
            e_context.action = EventAction.CONTINUE  # 事件继续，交付给下个插件或默认逻辑

    def get_help_text(self, **kwargs):
        return "本插件会处理询问实时日期时间，天气，数学运算等问题，这些技能由您的百度智能对话UNIT决定\n"

    def get_token(self):
        """获取访问百度UUNIT 的access_token
        #param api_key: UNIT apk_key
        #param secret_key: UNIT secret_key
        Returns:
            string: access_token
        """
        url = f"https://aip.baidubce.com/oauth/2.0/token?client_id={self.api_key}&client_secret={self.secret_key}&grant_type=client_credentials"
        payload = ""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        response = requests.request("POST", url, headers=headers, data=payload)

        # print(response.text)
        return response.json()["access_token"]

    def getUnit(self, query):
        """
        NLU 解析version 3.0
        :param query: 用户的指令字符串
        :returns: UNIT 解析结果。如果解析失败，返回 None
        """

        url = f"https://aip.baidubce.com/rpc/2.0/unit/service/v3/chat?access_token={self.access_token}"
        request = {
            "query": query,
            "user_id": str(get_mac())[:32],
            "terminal_id": "88888",
        }
        body = {
            "log_id": str(uuid.uuid1()),
            "version": "3.0",
            "service_id": self.service_id,
            "session_id": str(uuid.uuid1()),
            "request": request,
        }
        try:
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=body, headers=headers)
            return json.loads(response.text)
        except Exception:
            return None

    def getUnit2(self, query):
        """
        NLU 解析 version 2.0

        :param query: 用户的指令字符串
        :returns: UNIT 解析结果。如果解析失败，返回 None
        """
        url = f"https://aip.baidubce.com/rpc/2.0/unit/service/chat?access_token={self.access_token}"
        request = {"query": query, "user_id": str(get_mac())[:32]}
        body = {
            "log_id": str(uuid.uuid1()),
            "version": "2.0",
            "service_id": self.service_id,
            "session_id": str(uuid.uuid1()),
            "request": request,
        }
        try:
            headers = {"Content-Type": "application/json"}
            response = requests.post(url, json=body, headers=headers)
            return json.loads(response.text)
        except Exception:
            return None

    def getIntent(self, parsed):
        """
        提取意图

        :param parsed: UNIT 解析结果
        :returns: 意图数组
        """
        if (
            not parsed
            or "result" not in parsed
            or "response_list" not in parsed["result"]
        ):
            return ""
        try:
            return parsed["result"]["response_list"][0]["schema"]["intent"]
        except Exception as e:
            logger.warning(e)
            return ""

    def hasIntent(self, parsed, intent):
        """
        判断是否包含某个意图

        :param parsed: UNIT 解析结果
        :param intent: 意图的名称
        :returns: True: 包含; False: 不包含
        """
        if parsed and "result" in parsed and "response_list" in parsed["result"]:
            response_list = parsed["result"]["response_list"]
            for response in response_list:
                if "schema" in response and "intent" in response["schema"] and response["schema"]["intent"] == intent:
                    return True
        return False

    def getSlots(self, parsed, intent=""):
        """
            提取某个意图的所有词槽

            :param parsed: UNIT 解析结果
            :param intent: 意图的名称
            :returns: 词槽列表。你可以通过 name 属性筛选词槽，
        再通过 normalized_word 属性取出相应的值
        """
        if parsed and "result" in parsed and "response_list" in parsed["result"]:
            response_list = parsed["result"]["response_list"]
            if intent == "":
                try:
                    return parsed["result"]["response_list"][0]["schema"]["slots"]
                except Exception as e:
                    logger.warning(e)
                    return []
            for response in response_list:
                if "schema" in response and "intent" in response["schema"] and "slots" in response["schema"] and response["schema"]["intent"] == intent:
                    return response["schema"]["slots"]
        return []

    def getSlotWords(self, parsed, intent, name):
        """
        找出命中某个词槽的内容

        :param parsed: UNIT 解析结果
        :param intent: 意图的名称
        :param name: 词槽名
        :returns: 命中该词槽的值的列表。
        """
        slots = self.getSlots(parsed, intent)
        return [slot["normalized_word"] for slot in slots if slot["name"] == name]

    def getSayByConfidence(self, parsed):
        """
        提取 UNIT 置信度最高的回复文本

        :param parsed: UNIT 解析结果
        :returns: UNIT 的回复文本
        """
        if (
            not parsed
            or "result" not in parsed
            or "response_list" not in parsed["result"]
        ):
            return ""
        response_list = parsed["result"]["response_list"]
        answer = {}
        for response in response_list:
            if (
                "schema" in response
                and "intent_confidence" in response["schema"]
                and (not answer or response["schema"]["intent_confidence"] > answer["schema"]["intent_confidence"])
            ):
                answer = response
        return answer["action_list"][0]["say"]

    def getSay(self, parsed, intent=""):
        """
        提取 UNIT 的回复文本

        :param parsed: UNIT 解析结果
        :param intent: 意图的名称
        :returns: UNIT 的回复文本
        """
        if parsed and "result" in parsed and "response_list" in parsed["result"]:
            response_list = parsed["result"]["response_list"]
            if intent == "":
                try:
                    return response_list[0]["action_list"][0]["say"]
                except Exception as e:
                    logger.warning(e)
                    return ""
            for response in response_list:
                if "schema" in response and "intent" in response["schema"] and response["schema"]["intent"] == intent:
                    try:
                        return response["action_list"][0]["say"]
                    except Exception as e:
                        logger.warning(e)
                        return ""
        return ""
