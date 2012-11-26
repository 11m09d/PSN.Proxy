import sys
import os
import urlparse
import re
import subprocess
import time

from twisted.web.http import HTTPClient, HTTPFactory
from twisted.web.proxy import ProxyRequest, Proxy 
from twisted.web import static,server,resource
from twisted.protocols.basic import FileSender
from twisted.internet import reactor,threads
from twisted.internet.protocol import ClientFactory, Protocol
from twisted.internet.task import deferLater
from twisted.application.internet import TimerService

from lixian_api import LiXianAPI

#from twisted.python import log

#log.startLogging(sys.stdout)
__version__ = '0.0.1'
VERSION = 'PSN Proxy/'+__version__
PROXY_HOST = "192.168.1.200"
PROXY_PORT = 8080
XUNLEI_USERNAME = ''
XUNLEI_PASSWORD = ''
xunlei = LiXianAPI()

class LocalFile(static.File):

    def getFileName(self,url):
        i = url.rfind('/')
        if i == -1:
            return ''
        i += 1
        e = url.rfind('?',i)
        if e == -1:
            e = len(url)
        return url[i:e]

    def transfer(self, request):
        print 'begin transfer\n'
        fp = open('./cache/' + self.getFileName(request.uri), 'rb')
        d = FileSender().beginFileTransfer(fp, request)
        def cbFinished(ignored):
            fp.close()
            request.finish()
            print 'end transfer\n'
        d.addBoth(cbFinished)

    def download(self, request):
        xunlei.add_task(request.uri)
        url = xunlei.get_task_list(10,2)[0]['lixian_url']
        print url
        ret = subprocess.call('aria2c -s10 -x5 -k 10M --header "Cookie:gdriveid=' + xunlei.gdriveid + ';" -d ./cache/ "' + url + '"',shell=True)
        if ret == 0:
            print 'download completed!\n'
        else:
            print 'download failed!\n'

    def render_GET(self, request):
        request.setHeader('Content-Type', 'text/plain')
        t = 0
        if os.path.exists('./cache/' + self.getFileName(request.uri)):
            self.transfer(request)
        else:
            d = threads.deferToThread(self.download, request)
            #d = deferLater(reactor, t, self.download, request)
            d.addCallback(self.transfer, request)
        return server.NOT_DONE_YET

class TunnelProxyRequest (ProxyRequest): 
    res = LocalFile('./cache')
    
    def isReplace(self):
        p = re.compile('http://\S+playstation.net/\S+/\S+[.]pkg.*')
        if p.match(self.uri):
            return True
        p = re.compile('http://\S+playstation.net/\S+/\S+UPDAT[.]PUP.*')
        if p.match(self.uri):
            return True
        return False

    """ 
    A request processor which supports the TUNNEL method. 
    """ 
    def process(self): 
        print self.uri
        if self.isReplace():
            self.res.render_GET(self);
            #self.transport.loseConnection()
        else:
            if self.method.upper() == 'CONNECT': 
                self._process_connect() 
            else: 
                return ProxyRequest.process(self) 
 
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

def info():
    xvi = xunlei.get_vip_info()
    info = ''
    info += '------------------------------------------------------\n'
    info += 'PSN.Proxy Version    : %s\n' % (__version__)
    info += 'Listen Address       : %s:%d\n' % (PROXY_HOST,PROXY_PORT)
    info += 'Xunlei               : %s\n' % (XUNLEI_USERNAME)
    info += 'Xunlei Expired Date  : %s\n' % (xvi.get("expiredate", "unknow"))
    info += 'Xunlei Level         : %s\n' % (xvi.get("level", "0"))
    info += '------------------------------------------------------\n'
    return info

if __name__ == '__main__':
    reactor.listenTCP(8080, TunnelProxyFactory()) 
    if not xunlei.login(XUNLEI_USERNAME, XUNLEI_PASSWORD):
        print >> stderr, username, "login error" 
        sys.exit(3)
    else:
        print info()
    reactor.run()

