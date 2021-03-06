#/bin/usr/env python
#encoding: utf8
#author: psyche08<psyche08@gmail.com>

import sys
import os
import re
import subprocess
import ConfigParser
import getpass
import socket

from twisted.web import server,http,static
from twisted.web.http import HTTPFactory
from twisted.web.proxy import ProxyClient,ProxyRequest,Proxy 
from twisted.protocols.basic import FileSender
from twisted.internet import reactor,threads,defer
from twisted.internet.protocol import ClientFactory,Protocol
from twisted.internet.task import deferLater
from twisted.web.client import Agent

from lixian_api import LiXianAPI

__version__ = '0.1.1'
__config__ = 'proxy.ini'

def getFileName(url):
    i = url.rfind('/')
    if i == -1:
        return ''
    i += 1
    e = url.rfind('?',i)
    if e == -1:
        e = len(url)
    return url[i:e]

class LocalFile(static.File):

    def __init__(self,filepath):
        static.File.__init__(self, filepath)
        self.filepath = filepath
        self.contentTypes['.pkg'] = 'application/octet-stream'

    def transfer_failed(self, result, request):
        #print '[debug]LocalFile.transfer_failed_2(response, request)'
        request.setResponseCode(404)
        request.finish()

    def _fake_render(self, response, request):
        #print '[debug]LocalFile._fake_render(response, request)'
        self.restat(False)
        for header, value in response.headers.getAllRawHeaders():
            request.setHeader(header, value)

        request.setResponseCode(http.OK)

        #send response header
        request.write('')

        d = threads.deferToThread(self.download, request)
        d.addCallback(self.download_finish, request)

    def get_xunlei_url(self,request):
        common.xunlei.add_task(request.uri)
        tasks = common.xunlei.get_task_list(10,0)
        for task in tasks:
            #print task['url']
            if task['url'] == request.uri:
                if task['status'] != "finished":
                    #TODO
                    break
                return task['lixian_url']
        return request.uri

    def download(self, request):
        #print '[debug]LocalFile.download(request)'
        p = None
        if not common.has_download(self.filepath):
            ret = 0
            cmd = 'aria2c -c -s10 -x5 -k 10M -d %s -o %s "%s"' % (common.destdir, getFileName(request.uri), request.uri)
            if common.XUNLEI_ENABLE:
                cmd = 'aria2c -c -s10 -x5 -k 10M --header "Cookie:gdriveid=%s;" -d %s -o "%s" "%s"' % (common.xunlei.gdriveid, common.destdir, getFileName(request.uri), self.get_xunlei_url(request))
            #print '[debug]',cmd
            p = subprocess.Popen(cmd,shell=True)
            common.addDownloadList(self.filepath, p)
        else:
            p = common.downloadlist[self.filepath]
        
        ret = p.wait()
        common.delDownloadList(self.filepath)
        return ret

    def download_finish(self, result, request):
        if result == 0 and os.path.exists(self.filepath) and not os.path.exists(self.filepath + '.aria2'):
            try:
                fileForReading = self.openForReading()
            except IOError, e:
                import errno
                if e[0] == errno.EACCES:
                    return resource.ForbiddenResource().render(request)
                else:
                    raise

            producer = self.makeProducer(request, fileForReading)
            producer.start()
        else:
            print 'download failed'
            self.transfer_failed(None, request)
    
    def pre_render(self, request):
        #print '[debug]LocalFile.pre_render(request)'
        if os.path.exists(self.filepath) and not os.path.exists(self.filepath + '.aria2'):
            #print 'File already downloaded, begin to transfer...'
            self.render(request)
        else:
            agent = Agent(request.reactor)
            d = agent.request('HEAD', request.uri, request.requestHeaders.copy(), None)
            d.addCallback(self._fake_render, request)
            d.addErrback(self.transfer_failed, request)
        # and make sure the connection doesn't get closed
        return server.NOT_DONE_YET

class TunnelProxyRequest (ProxyRequest):

    def isReplace(self):
        for il in common.ignorelist:
            if self.uri == il:
                return False        
        for ul in common.urls:
            if self.uri == ul:
                return True
        for fi in common.filters:
            p = re.compile(fi[1])
            if p.match(self.uri):
                return True
        return False

    #Sometimes i get uri like this http://psp2-e.np.dl.playstation.nethttp://psp2-e.np.dl.playstation.net/
    #this is a temporary function
    def fixVitaURL(self):
        p = re.compile('^http://\S*[.]playstation[.]nethttp://\S*[.]playstation[.]net/S*')
        if p.match(self.uri):
            self.uri = self.uri[self.uri.find('http://',7):]
            print 'Psn.proxy Warning: Host psp2-e.np.dl.playstation.nethttp misformated, psn.proxy fixed it'

    def write(self, data):
        #if self.method.upper() == 'HEAD':
            #print 'debug TunnelProxyRequest.write',self.responseHeaders
        ProxyRequest.write(self,data)
        if self.method.upper() == 'HEAD' and self.isReplace() and self.responseHeaders.hasHeader('content-length'):
            #print self.responseHeaders.getRawHeaders('content-length')
            pkgsize = int(self.responseHeaders.getRawHeaders('content-length')[-1])
            if pkgsize < common.minsize:
                if not self.uri in common.ignorelist:
                    common.ignorelist.append(self.uri)
                    print 'Psn.proxy : this pkg is too small, ignore'


    """ 
    A request processor which supports the TUNNEL method. 
    """ 
    def process(self): 
        #fix for vita
        self.fixVitaURL()
        print self
        if self.isReplace() and self.method.upper() == "GET":
            filepath = os.path.join(common.destdir, getFileName(self.uri))
            lf = LocalFile(filepath)
            print 'Psn.proxy : download/using local file ',filepath
            lf.pre_render(self);
        else:
            if self.method.upper() == 'CONNECT': 
                self._process_connect() 
            else: 
                ProxyRequest.process(self) 
                #if the pkg is too smaller,there is no need to boost

    def _process_connect(self): 
        try: 
            host, portStr = self.uri.split(':', 1) 
            port = int(portStr) 
        except ValueError: 
            # Either the connect parameter is not HOST:PORT or PORT is 
            # not an integer, in which case this request is invalid. 
            self.setResponseCode(400) 
            self.finish() 
        else: 
            restrictedToPort = self.channel.factory.restrictedToPort 
            if (restrictedToPort is not None) and (port != restrictedToPort): 
                self.setResponseCode(403, 'Forbidden port') 
                self.finish() 
            else: 
                self.reactor.connectTCP(host, port, TunnelProtocolFactory(self, host, port)) 
 
 
class TunnelProxy (Proxy): 
    """ 
    This class implements a simple web proxy with CONNECT support. 

    It inherits from L{Proxy} and expects 
    L{twisted.web.proxy.TunnelProxyFactory} as a factory. 
 
        f = TunnelProxyFactory() 
 
    Make the TunnelProxyFactory a listener on a port as per usual, 
    and you have a fully-functioning web proxy which supports CONNECT. 
    This should support typical web usage with common browsers. 
 
    @ivar _tunnelproto: This is part of a private interface between 
        TunnelProxy and TunnelProtocol. This is either None or a 
        TunnelProtocol connected to a server due to a CONNECT request. 
        If this is set, then the stream from the user agent is forwarded 
        to the target HOST:PORT of the CONNECT request. 
    """ 
    requestFactory = TunnelProxyRequest 
 
    def __init__(self): 
        self._tunnelproto = None 
        Proxy.__init__(self) 
 
    def _registerTunnel(self, tunnelproto): 
        """ 
        This is a private interface for L{TunnelProtocol}.  This sets 
        L{_tunnelproto} to which to forward the stream from the user 
        agent.  This should only be set after the tunnel to the target 
        HOST:PORT is established. 
        """ 
        assert self._tunnelproto is None, 'Precondition failure: Multiple TunnelProtocols set: self._tunnelproto == %r; new tunnelproto == %r' % (self._tunnelproto, tunnelproto) 
        self._tunnelproto = tunnelproto 

    def dataReceived(self, data): 
        """ 
        If there is a tunnel connection, forward the stream; otherwise 
        behave just like Proxy. 
        """ 
        if self._tunnelproto is None: 
            Proxy.dataReceived(self, data) 
        else: 
            self._tunnelproto.transport.write(data) 

 
 
class TunnelProxyFactory (HTTPFactory): 
    """ 
    Factory for an HTTP proxy. 
 
    @ivar restrictedToPort: Only CONNECT requests to this port number 
        are allowed.  This may be None, in which case any port is allowed. 
    @type restrictedToPort: L{int} or None 
    """ 
 
    protocol = TunnelProxy 
 
    def __init__(self, logPath=None, timeout=60*60*12, restrictedToPort=443): 
        """ 
        @param logPath: The same as for HTTPFactory. 
        @param timeout: The same as for HTTPFactory. 
 
        @param restrictedToPort: Only CONNECT requests to this port number 
            are allowed.  This may be None, in which case any port 
            is allowed. 
        @type restrictedToPort: C{int} or None 
        """ 
        assert restrictedToPort is None or type(restrictedToPort) is int, 'Invalid restrictedToPort value: %r' % (restrictedToPort,) 
 
        self.restrictedToPort = restrictedToPort 
        HTTPFactory.__init__(self, logPath, timeout) 
 
 
 
class TunnelProtocol (Protocol): 
    """ 
    When a user agent makes a CONNECT request to a TunnelProxy, this 
    protocol implements the proxy's client logic. 
 
    When the proxy connects to the target host, it responds to the user 
    agent's request with an HTTP 200.  After that, it relays the stream 
    from the target host back through the connection to the user agent. 
 
    BUG: Verify that the 200 response meets the RFCs (or the common 
    practice if it deviates from the specification). 
    """ 
    # BUG: Handle early disconnects and other edge cases. 
 
    def __init__(self, request): 
        self._request = request 
        self._channel = request.channel 
        self._peertransport = request.channel.transport 
     
    def connectionMade(self): 
        # BUG: Check this against RFCs or common implementation: 
        self._channel._registerTunnel(self) 
        self._request.setResponseCode(200, 'Connected') 
 
        # Write nothing to trigger sending the response headers, but do 
        # not call finish, which may close the connection: 
        self._request.write('') 
 
    def dataReceived(self, data): 
        self._peertransport.write(data) 
 
class TunnelProtocolFactory (ClientFactory): 
    protocol = TunnelProtocol 
 
    def __init__(self, request, host, port): 
        self._request = request 
 
    def buildProtocol(self, addr): 
        return self.protocol(self._request) 
 
    def clientConnectionFailed(self, connector, reason): 
        self._request.setResponseCode(501, 'Gateway error') 
        self._request.finish() 

class Common:
    
    def __init__(self,username = None,password = None):
        ConfigParser.RawConfigParser.OPTCRE = re.compile(r'(?P<option>[^=\s][^=]*)\s*(?P<vi>[=])\s*(?P<value>.*)$')
        self.CONFIG = ConfigParser.ConfigParser()
        self.CONFIG.read(os.path.join(os.path.dirname(__file__), __config__))

        self.LISTEN_IP = self.CONFIG.get('listen', 'ip')
        self.LISTEN_PORT = self.CONFIG.getint('listen', 'port')

        self.XUNLEI_ENABLE = self.CONFIG.getboolean('xunlei', 'enable')
        if self.XUNLEI_ENABLE:
            if username != None:
                self.USERNAME = username
            else:
                self.USERNAME = self.CONFIG.get('xunlei', 'username')
            if password != None:
                self.PASSWORD = password
            else:
                self.PASSWORD = self.CONFIG.get('xunlei', 'password')

        self.urls = self.CONFIG.items('url')
        self.filters = self.CONFIG.items('filter')

        self.destdir = os.path.join(os.path.dirname(__file__), 'cache')

        self.minsize = self.CONFIG.getint('download', 'minsize')

        self.downloadlist = {}      
        self.ignorelist = []        
        
        self.xunlei = LiXianAPI()

        if self.XUNLEI_ENABLE:
            if self.USERNAME == '' or self.PASSWORD == '':
                self.USERNAME = raw_input('Username: ')
                self.PASSWORD = getpass.getpass('Password: ')
            try:
                if not self.xunlei.login(self.USERNAME, self.PASSWORD):
                    print self.USERNAME, "login error"
                    key = raw_input("Press enter key to exit...")
                    sys.exit(-1)
            except:
                pass
        
        print self.info()
        
    def info(self):
        xvi = self.xunlei.get_vip_info()
        info = ''
        info += '------------------------------------------------------\n'
        info += 'PSN.Proxy Version    : %s\n' % (__version__)
        info += 'Listen Address       : %s:%d\n' % (socket.gethostbyname(socket.gethostname()), self.LISTEN_PORT)
        if self.XUNLEI_ENABLE:
            info += 'Xunlei User          : %s\n' % (self.USERNAME)
            info += 'Xunlei Expired Date  : %s\n' % (xvi.get("expiredate", "unknow"))
            info += 'Xunlei Level         : %s\n' % (xvi.get("level", "0"))
        info += '------------------------------------------------------\n'
        return info

    def has_download(self, key):
        return self.downloadlist.has_key(key)
        
    def addDownloadList(self, key, value):
        self.downloadlist[key] = value

    def delDownloadList(self, key):
        if self.downloadlist.has_key(key):
            del self.downloadlist[key]

common = None

if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == '-h':
        print 'Usage:python proxy.py <username> <password>'
        sys.exit(0)

    global __file__
    if os.path.islink(__file__):
        __file__ = getattr(os, 'readlink', lambda x:x)(__file__)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if len(sys.argv) == 3:
        common = Common(sys.argv[1],sys.argv[2])
    else:
        common = Common()
        
    reactor.listenTCP(common.LISTEN_PORT, TunnelProxyFactory()) 
    reactor.run()

