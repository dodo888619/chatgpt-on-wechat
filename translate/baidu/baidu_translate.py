# -*- coding: utf-8 -*-

import random
from hashlib import md5

import requests

from config import conf
from translate.translator import Translator


class BaiduTranslator(Translator):
    def __init__(self) -> None:
        super().__init__()
        path = "/api/trans/vip/translate"
        self.url = f"http://api.fanyi.baidu.com{path}"
        self.appid = conf().get("baidu_translate_app_id")
        self.appkey = conf().get("baidu_translate_app_key")
        if not self.appid or not self.appkey:
            raise Exception("baidu translate appid or appkey not set")

    # For list of language codes, please refer to `https://api.fanyi.baidu.com/doc/21`, need to convert to ISO 639-1 codes
    def translate(self, query: str, from_lang: str = "", to_lang: str = "en") -> str:
        if not from_lang:
            from_lang = "auto"  # baidu suppport auto detect
        salt = random.randint(32768, 65536)
        sign = self.make_md5(f"{self.appid}{query}{salt}{self.appkey}")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        payload = {"appid": self.appid, "q": query, "from": from_lang, "to": to_lang, "salt": salt, "sign": sign}

        retry_cnt = 3
        while retry_cnt:
            r = requests.post(self.url, params=payload, headers=headers)
            result = r.json()
            errcode = result.get("error_code", "52000")
            if errcode == "52000":
                break
            if errcode in ["52001", "52002"]:
                retry_cnt -= 1
            else:
                raise Exception(result["error_msg"])
        return "\n".join([item["dst"] for item in result["trans_result"]])

    def make_md5(self, s, encoding="utf-8"):
        return md5(s.encode(encoding)).hexdigest()
