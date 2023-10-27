import os, time, re, io
import json
import mimetypes, hashlib
import logging
from collections import OrderedDict

import requests

from .. import config, utils
from ..returnvalues import ReturnValue
from ..storage import templates
from .contact import update_local_uin

logger = logging.getLogger('itchat')

def load_messages(core):
    core.send_raw_msg = send_raw_msg
    core.send_msg     = send_msg
    core.upload_file  = upload_file
    core.send_file    = send_file
    core.send_image   = send_image
    core.send_video   = send_video
    core.send         = send
    core.revoke       = revoke

def get_download_fn(core, url, msgId):
    def download_fn(downloadDir=None):
        params = {
            'msgid': msgId,
            'skey': core.loginInfo['skey'],}
        headers = { 'User-Agent' : config.USER_AGENT }
        r = core.s.get(url, params=params, stream=True, headers = headers)
        tempStorage = io.BytesIO()
        for block in r.iter_content(1024):
            tempStorage.write(block)
        if downloadDir is None:
            return tempStorage.getvalue()
        with open(downloadDir, 'wb') as f:
            f.write(tempStorage.getvalue())
        tempStorage.seek(0)
        return ReturnValue({'BaseResponse': {
            'ErrMsg': 'Successfully downloaded',
            'Ret': 0, },
            'PostFix': utils.get_image_postfix(tempStorage.read(20)), })
    return download_fn

def produce_msg(core, msgList):
    ''' for messages types
     * 40 msg, 43 videochat, 50 VOIPMSG, 52 voipnotifymsg
     * 53 webwxvoipnotifymsg, 9999 sysnotice
    '''
    rl = []
    srl = [40, 43, 50, 52, 53, 9999]
    for m in msgList:
        # get actual opposite
        if m['FromUserName'] == core.storageClass.userName:
            actualOpposite = m['ToUserName']
        else:
            actualOpposite = m['FromUserName']
        # produce basic message
        if '@@' in m['FromUserName'] or '@@' in m['ToUserName']:
            produce_group_chat(core, m)
        else:
            utils.msg_formatter(m, 'Content')
        # set user of msg
        if '@@' in actualOpposite:
            m['User'] = core.search_chatrooms(userName=actualOpposite) or \
                templates.Chatroom({'UserName': actualOpposite})
            # we don't need to update chatroom here because we have
            # updated once when producing basic message
        elif actualOpposite in ('filehelper', 'fmessage'):
            m['User'] = templates.User({'UserName': actualOpposite})
        else:
            m['User'] = core.search_mps(userName=actualOpposite) or \
                core.search_friends(userName=actualOpposite) or \
                templates.User(userName=actualOpposite)
            # by default we think there may be a user missing not a mp
        m['User'].core = core
        if m['MsgType'] == 1: # words
            if m['Url']:
                regx = r'(.+?\(.+?\))'
                data = re.search(regx, m['Content'])
                data = 'Map' if data is None else data.group(1)
                msg = {
                    'Type': 'Map',
                    'Text': data,}
            else:
                msg = {
                    'Type': 'Text',
                    'Text': m['Content'],}
        elif m['MsgType'] in [3, 47]: # picture
            download_fn = get_download_fn(
                core, f"{core.loginInfo['url']}/webwxgetmsgimg", m['NewMsgId']
            )
            msg = {
                'Type': 'Picture',
                'FileName': f"{time.strftime('%y%m%d-%H%M%S', time.localtime())}.{'png' if m['MsgType'] == 3 else 'gif'}",
                'Text': download_fn,
            }
        elif m['MsgType'] == 34: # voice
            download_fn = get_download_fn(
                core, f"{core.loginInfo['url']}/webwxgetvoice", m['NewMsgId']
            )
            msg = {
                'Type': 'Recording',
                'FileName': f"{time.strftime('%y%m%d-%H%M%S', time.localtime())}.mp3",
                'Text': download_fn,
            }
        elif m['MsgType'] == 37: # friends
            m['User']['UserName'] = m['RecommendInfo']['UserName']
            msg = {
                'Type': 'Friends',
                'Text': {
                    'status'        : m['Status'],
                    'userName'      : m['RecommendInfo']['UserName'],
                    'verifyContent' : m['Ticket'],
                    'autoUpdate'    : m['RecommendInfo'], }, }
            m['User'].verifyDict = msg['Text']
        elif m['MsgType'] == 42: # name card
            msg = {
                'Type': 'Card',
                'Text': m['RecommendInfo'], }
        elif m['MsgType'] in (43, 62): # tiny video
            msgId = m['MsgId']
            def download_video(videoDir=None):
                url = f"{core.loginInfo['url']}/webwxgetvideo"
                params = {
                    'msgid': msgId,
                    'skey': core.loginInfo['skey'],}
                headers = {'Range': 'bytes=0-', 'User-Agent' : config.USER_AGENT }
                r = core.s.get(url, params=params, headers=headers, stream=True)
                tempStorage = io.BytesIO()
                for block in r.iter_content(1024):
                    tempStorage.write(block)
                if videoDir is None:
                    return tempStorage.getvalue()
                with open(videoDir, 'wb') as f:
                    f.write(tempStorage.getvalue())
                return ReturnValue({'BaseResponse': {
                    'ErrMsg': 'Successfully downloaded',
                    'Ret': 0, }})

            msg = {
                'Type': 'Video',
                'FileName': f"{time.strftime('%y%m%d-%H%M%S', time.localtime())}.mp4",
                'Text': download_video,
            }
        elif m['MsgType'] == 49: # sharing
            if m['AppMsgType'] == 0: # chat history
                msg = {
                    'Type': 'Note',
                    'Text': m['Content'], }
            elif m['AppMsgType'] == 6:
                rawMsg = m
                cookiesList = dict(core.s.cookies.items())
                def download_atta(attaDir=None):
                    url = core.loginInfo['fileUrl'] + '/webwxgetmedia'
                    params = {
                        'sender': rawMsg['FromUserName'],
                        'mediaid': rawMsg['MediaId'],
                        'filename': rawMsg['FileName'],
                        'fromuser': core.loginInfo['wxuin'],
                        'pass_ticket': 'undefined',
                        'webwx_data_ticket': cookiesList['webwx_data_ticket'],}
                    headers = { 'User-Agent' : config.USER_AGENT }
                    r = core.s.get(url, params=params, stream=True, headers=headers)
                    tempStorage = io.BytesIO()
                    for block in r.iter_content(1024):
                        tempStorage.write(block)
                    if attaDir is None:
                        return tempStorage.getvalue()
                    with open(attaDir, 'wb') as f:
                        f.write(tempStorage.getvalue())
                    return ReturnValue({'BaseResponse': {
                        'ErrMsg': 'Successfully downloaded',
                        'Ret': 0, }})

                msg = {
                    'Type': 'Attachment',
                    'Text': download_atta, }
            elif m['AppMsgType'] == 8:
                download_fn = get_download_fn(
                    core,
                    f"{core.loginInfo['url']}/webwxgetmsgimg",
                    m['NewMsgId'],
                )
                msg = {
                    'Type': 'Picture',
                    'FileName': f"{time.strftime('%y%m%d-%H%M%S', time.localtime())}.gif",
                    'Text': download_fn,
                }
            elif m['AppMsgType'] == 17:
                msg = {
                    'Type': 'Note',
                    'Text': m['FileName'], }
            elif m['AppMsgType'] == 2000:
                regx = r'\[CDATA\[(.+?)\][\s\S]+?\[CDATA\[(.+?)\]'
                data = re.search(regx, m['Content'])
                if data:
                    data = data.group(2).split(u'\u3002')[0]
                else:
                    data = 'You may found detailed info in Content key.'
                msg = {
                    'Type': 'Note',
                    'Text': data, }
            else:
                msg = {
                    'Type': 'Sharing',
                    'Text': m['FileName'], }
        elif m['MsgType'] == 51: # phone init
            msg = update_local_uin(core, m)
        elif m['MsgType'] == 10000:
            msg = {
                'Type': 'Note',
                'Text': m['Content'],}
        elif m['MsgType'] == 10002:
            regx = r'\[CDATA\[(.+?)\]\]'
            data = re.search(regx, m['Content'])
            data = 'System message' if data is None else data.group(1).replace('\\', '')
            msg = {
                'Type': 'Note',
                'Text': data, }
        elif m['MsgType'] in srl:
            msg = {
                'Type': 'Useless',
                'Text': 'UselessMsg', }
        else:
            logger.debug('Useless message received: %s\n%s' % (m['MsgType'], str(m)))
            msg = {
                'Type': 'Useless',
                'Text': 'UselessMsg', }
        m = dict(m, **msg)
        rl.append(m)
    return rl

def produce_group_chat(core, msg):
    if r := re.match('(@[0-9a-z]*?):<br/>(.*)$', msg['Content']):
        actualUserName, content = r.groups()
        chatroomUserName = msg['FromUserName']
    elif msg['FromUserName'] == core.storageClass.userName:
        actualUserName = core.storageClass.userName
        content = msg['Content']
        chatroomUserName = msg['ToUserName']
    else:
        msg['ActualUserName'] = core.storageClass.userName
        msg['ActualNickName'] = core.storageClass.nickName
        msg['IsAt'] = False
        utils.msg_formatter(msg, 'Content')
        return
    chatroom = core.storageClass.search_chatrooms(userName=chatroomUserName)
    member = utils.search_dict_list((chatroom or {}).get(
        'MemberList') or [], 'UserName', actualUserName)
    if member is None:
        chatroom = core.update_chatroom(chatroomUserName)
        member = utils.search_dict_list((chatroom or {}).get(
            'MemberList') or [], 'UserName', actualUserName)
    if member is None:
        logger.debug(f'chatroom member fetch failed with {actualUserName}')
        msg['ActualNickName'] = ''
        msg['IsAt'] = False
    else:
        msg['ActualNickName'] = member.get('DisplayName', '') or member['NickName']
        atFlag = '@' + (chatroom['Self'].get('DisplayName', '') or core.storageClass.nickName)
        msg['IsAt'] = (
            (atFlag + (u'\u2005' if u'\u2005' in msg['Content'] else ' '))
            in msg['Content'] or msg['Content'].endswith(atFlag))
    msg['ActualUserName'] = actualUserName
    msg['Content']        = content
    utils.msg_formatter(msg, 'Content')

def send_raw_msg(self, msgType, content, toUserName):
    url = f"{self.loginInfo['url']}/webwxsendmsg"
    data = {
        'BaseRequest': self.loginInfo['BaseRequest'],
        'Msg': {
            'Type': msgType,
            'Content': content,
            'FromUserName': self.storageClass.userName,
            'ToUserName': (toUserName if toUserName else self.storageClass.userName),
            'LocalID': int(time.time() * 1e4),
            'ClientMsgId': int(time.time() * 1e4),
            },
        'Scene': 0, }
    headers = { 'ContentType': 'application/json; charset=UTF-8', 'User-Agent' : config.USER_AGENT }
    r = self.s.post(url, headers=headers,
        data=json.dumps(data, ensure_ascii=False).encode('utf8'))
    return ReturnValue(rawResponse=r)

def send_msg(self, msg='Test Message', toUserName=None):
    logger.debug(f'Request to send a text message to {toUserName}: {msg}')
    return self.send_raw_msg(1, msg, toUserName)

def _prepare_file(fileDir, file_=None):
    if file_:
        if hasattr(file_, 'read'):
            file_ = file_.read()
        else:
            return ReturnValue({'BaseResponse': {
                'ErrMsg': 'file_ param should be opened file',
                'Ret': -1005, }})
    else:
        if not utils.check_file(fileDir):
            return ReturnValue({'BaseResponse': {
                'ErrMsg': 'No file found in specific dir',
                'Ret': -1002, }})
        with open(fileDir, 'rb') as f:
            file_ = f.read()
    fileDict = {'fileSize': len(file_), 'fileMd5': hashlib.md5(file_).hexdigest()}
    fileDict['file_'] = io.BytesIO(file_)
    return fileDict

def upload_file(self, fileDir, isPicture=False, isVideo=False,
        toUserName='filehelper', file_=None, preparedFile=None):
    logger.debug(
        f"Request to upload a {'picture' if isPicture else 'video' if isVideo else 'file'}: {fileDir}"
    )
    if not preparedFile:
        preparedFile = _prepare_file(fileDir, file_)
    if not preparedFile:
        return preparedFile
    fileSize, fileMd5, file_ = \
        preparedFile['fileSize'], preparedFile['fileMd5'], preparedFile['file_']
    fileSymbol = 'pic' if isPicture else 'video' if isVideo else'doc'
    chunks = int((fileSize - 1) / 524288) + 1
    clientMediaId = int(time.time() * 1e4)
    uploadMediaRequest = json.dumps(OrderedDict([
        ('UploadType', 2),
        ('BaseRequest', self.loginInfo['BaseRequest']),
        ('ClientMediaId', clientMediaId),
        ('TotalLen', fileSize),
        ('StartPos', 0),
        ('DataLen', fileSize),
        ('MediaType', 4),
        ('FromUserName', self.storageClass.userName),
        ('ToUserName', toUserName),
        ('FileMd5', fileMd5)]
        ), separators = (',', ':'))
    r = {'BaseResponse': {'Ret': -1005, 'ErrMsg': 'Empty file detected'}}
    for chunk in range(chunks):
        r = upload_chunk_file(self, fileDir, fileSymbol, fileSize,
            file_, chunk, chunks, uploadMediaRequest)
    file_.close()
    return ReturnValue(r) if isinstance(r, dict) else ReturnValue(rawResponse=r)

def upload_chunk_file(core, fileDir, fileSymbol, fileSize,
        file_, chunk, chunks, uploadMediaRequest):
    url = core.loginInfo.get('fileUrl', core.loginInfo['url']) + \
        '/webwxuploadmedia?f=json'
    # save it on server
    cookiesList = dict(core.s.cookies.items())
    fileType = mimetypes.guess_type(fileDir)[0] or 'application/octet-stream'
    fileName = utils.quote(os.path.basename(fileDir))
    files = OrderedDict([
        ('id', (None, 'WU_FILE_0')),
        ('name', (None, fileName)),
        ('type', (None, fileType)),
        ('lastModifiedDate', (None, time.strftime('%a %b %d %Y %H:%M:%S GMT+0800 (CST)'))),
        ('size', (None, str(fileSize))),
        ('chunks', (None, None)),
        ('chunk', (None, None)),
        ('mediatype', (None, fileSymbol)),
        ('uploadmediarequest', (None, uploadMediaRequest)),
        ('webwx_data_ticket', (None, cookiesList['webwx_data_ticket'])),
        ('pass_ticket', (None, core.loginInfo['pass_ticket'])),
        ('filename' , (fileName, file_.read(524288), 'application/octet-stream'))])
    if chunks == 1:
        del files['chunk']; del files['chunks']
    else:
        files['chunk'], files['chunks'] = (None, str(chunk)), (None, str(chunks))
    headers = { 'User-Agent' : config.USER_AGENT }
    return core.s.post(url, files=files, headers=headers, timeout=config.TIMEOUT)

def send_file(self, fileDir, toUserName=None, mediaId=None, file_=None):
    logger.debug(
        f'Request to send a file(mediaId: {mediaId}) to {toUserName}: {fileDir}'
    )
    if hasattr(fileDir, 'read'):
        return ReturnValue({'BaseResponse': {
            'ErrMsg': 'fileDir param should not be an opened file in send_file',
            'Ret': -1005, }})
    if toUserName is None:
        toUserName = self.storageClass.userName
    preparedFile = _prepare_file(fileDir, file_)
    if not preparedFile:
        return preparedFile
    fileSize = preparedFile['fileSize']
    if mediaId is None:
        r = self.upload_file(fileDir, preparedFile=preparedFile)
        if r:
            mediaId = r['MediaId']
        else:
            return r
    url = f"{self.loginInfo['url']}/webwxsendappmsg?fun=async&f=json"
    data = {
        'BaseRequest': self.loginInfo['BaseRequest'],
        'Msg': {
            'Type': 6,
            'Content': (
                (
                    f"<appmsg appid='wxeb7ec651dd0aefa9' sdkver=''><title>{os.path.basename(fileDir)}</title><des></des><action></action><type>6</type><content></content><url></url><lowurl></lowurl>"
                    + f"<appattach><totallen>{str(fileSize)}</totallen><attachid>{mediaId}</attachid>"
                )
                + f"<fileext>{os.path.splitext(fileDir)[1].replace('.', '')}</fileext></appattach><extinfo></extinfo></appmsg>"
            ),
            'FromUserName': self.storageClass.userName,
            'ToUserName': toUserName,
            'LocalID': int(time.time() * 1e4),
            'ClientMsgId': int(time.time() * 1e4),
        },
        'Scene': 0,
    }
    headers = {
        'User-Agent': config.USER_AGENT,
        'Content-Type': 'application/json;charset=UTF-8', }
    r = self.s.post(url, headers=headers,
        data=json.dumps(data, ensure_ascii=False).encode('utf8'))
    return ReturnValue(rawResponse=r)

def send_image(self, fileDir=None, toUserName=None, mediaId=None, file_=None):
    logger.debug(
        f'Request to send a image(mediaId: {mediaId}) to {toUserName}: {fileDir}'
    )
    if not fileDir and not file_:
        return ReturnValue({'BaseResponse': {
            'ErrMsg': 'Either fileDir or file_ should be specific',
            'Ret': -1005, }})
    if hasattr(fileDir, 'read'):
        file_, fileDir = fileDir, None
    if fileDir is None:
        fileDir = 'tmp.jpg' # specific fileDir to send gifs
    if toUserName is None:
        toUserName = self.storageClass.userName
    if mediaId is None:
        r = self.upload_file(fileDir, isPicture=fileDir[-4:] != '.gif', file_=file_)
        if r:
            mediaId = r['MediaId']
        else:
            return r
    url = f"{self.loginInfo['url']}/webwxsendmsgimg?fun=async&f=json"
    data = {
        'BaseRequest': self.loginInfo['BaseRequest'],
        'Msg': {
            'Type': 3,
            'MediaId': mediaId,
            'FromUserName': self.storageClass.userName,
            'ToUserName': toUserName,
            'LocalID': int(time.time() * 1e4),
            'ClientMsgId': int(time.time() * 1e4), },
        'Scene': 0, }
    if fileDir[-4:] == '.gif':
        url = f"{self.loginInfo['url']}/webwxsendemoticon?fun=sys"
        data['Msg']['Type'] = 47
        data['Msg']['EmojiFlag'] = 2
    headers = {
        'User-Agent': config.USER_AGENT,
        'Content-Type': 'application/json;charset=UTF-8', }
    r = self.s.post(url, headers=headers,
        data=json.dumps(data, ensure_ascii=False).encode('utf8'))
    return ReturnValue(rawResponse=r)

def send_video(self, fileDir=None, toUserName=None, mediaId=None, file_=None):
    logger.debug(
        f'Request to send a video(mediaId: {mediaId}) to {toUserName}: {fileDir}'
    )
    if not fileDir and not file_:
        return ReturnValue({'BaseResponse': {
            'ErrMsg': 'Either fileDir or file_ should be specific',
            'Ret': -1005, }})
    if hasattr(fileDir, 'read'):
        file_, fileDir = fileDir, None
    if fileDir is None:
        fileDir = 'tmp.mp4' # specific fileDir to send other formats
    if toUserName is None:
        toUserName = self.storageClass.userName
    if mediaId is None:
        r = self.upload_file(fileDir, isVideo=True, file_=file_)
        if r:
            mediaId = r['MediaId']
        else:
            return r
    url = f"{self.loginInfo['url']}/webwxsendvideomsg?fun=async&f=json&pass_ticket={self.loginInfo['pass_ticket']}"
    data = {
        'BaseRequest': self.loginInfo['BaseRequest'],
        'Msg': {
            'Type'         : 43,
            'MediaId'      : mediaId,
            'FromUserName' : self.storageClass.userName,
            'ToUserName'   : toUserName,
            'LocalID'      : int(time.time() * 1e4),
            'ClientMsgId'  : int(time.time() * 1e4), },
        'Scene': 0, }
    headers = {
        'User-Agent' : config.USER_AGENT,
        'Content-Type': 'application/json;charset=UTF-8', }
    r = self.s.post(url, headers=headers,
        data=json.dumps(data, ensure_ascii=False).encode('utf8'))
    return ReturnValue(rawResponse=r)

def send(self, msg, toUserName=None, mediaId=None):
    if not msg:
        r = ReturnValue({'BaseResponse': {
            'ErrMsg': 'No message.',
            'Ret': -1005, }})
    elif msg[:5] == '@fil@':
        if mediaId is None:
            r = self.send_file(msg[5:], toUserName)
        else:
            r = self.send_file(msg[5:], toUserName, mediaId)
    elif msg[:5] == '@img@':
        if mediaId is None:
            r = self.send_image(msg[5:], toUserName)
        else:
            r = self.send_image(msg[5:], toUserName, mediaId)
    elif msg[:5] == '@msg@':
        r = self.send_msg(msg[5:], toUserName)
    elif msg[:5] == '@vid@':
        if mediaId is None:
            r = self.send_video(msg[5:], toUserName)
        else:
            r = self.send_video(msg[5:], toUserName, mediaId)
    else:
        r = self.send_msg(msg, toUserName)
    return r

def revoke(self, msgId, toUserName, localId=None):
    url = f"{self.loginInfo['url']}/webwxrevokemsg"
    data = {
        'BaseRequest': self.loginInfo['BaseRequest'],
        "ClientMsgId": localId or str(time.time() * 1e3),
        "SvrMsgId": msgId,
        "ToUserName": toUserName}
    headers = {
        'ContentType': 'application/json; charset=UTF-8',
        'User-Agent' : config.USER_AGENT }
    r = self.s.post(url, headers=headers,
        data=json.dumps(data, ensure_ascii=False).encode('utf8'))
    return ReturnValue(rawResponse=r)
