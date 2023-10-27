import time

from elevenlabs import set_api_key,generate

from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from voice.voice import Voice
from config import conf

XI_API_KEY = conf().get("xi_api_key")
set_api_key(XI_API_KEY)
name = conf().get("xi_voice_id")

class ElevenLabsVoice(Voice):

    def __init__(self):
        pass

    def voiceToText(self, voice_file):
        pass

    def textToVoice(self, text):
        audio = generate(
            text=text,
            voice=name,
            model='eleven_multilingual_v1'
        )
        fileName = f"{TmpDir().path()}reply-{int(time.time())}-{str(hash(text) & 2147483647)}.mp3"
        with open(fileName, "wb") as f:
            f.write(audio)
        logger.info(f"[ElevenLabs] textToVoice text={text} voice file name={fileName}")
        return Reply(ReplyType.VOICE, fileName)