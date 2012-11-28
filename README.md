psn.proxy  
=========
psn.proxy 是利用迅雷离线加速PSN下载的工具  

离线迅雷部分代码基于binux的lixian.xunlei项目<https://github.com/binux/lixian.xunlei>  

下载将调用aria2c，请保证aria2c在命令行下可用

下载  
=========
0.1版本下载：<https://github.com/downloads/psyche08/psn.proxy/PSN.Proxy.zip>  

Usage  
=========
源代码版本：
python proxy.py  
or  
python proxy.py xunlei.username xunlei.password
  
Feature  
=========
1、对符合条件的URL，使用迅雷离线下载完成后再传给ps设备  
2、可以通过proxy.ini配置端口设置、迅雷账号、以及自动下载的过滤条件  
  
TODO List
=========
1、在psn store出现未知错误  
2、离线迅雷未能立即下载完成的情况下的处理  
3、缓存文件目录可配置  
4、图形界面  
  
License  
=========
psn.proxy is licensed under GNU Lesser General Public License. You may get a copy of the GNU Lesser General Public License from <http://www.gnu.org/licenses/lgpl.txt>

