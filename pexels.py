# coding: utf8

import urllib, urllib2, string
import requests
import urlparse
import os, sys, time
import codecs
import os
import statvfs
from hashids import Hashids
from bs4 import BeautifulSoup

from config import (
    QINIU_ACCESS_KEY, QINIU_SECRET_KEY, QINIU_BUCKET, QINIU_BASE_URL,
    BASE_OUTPUT_DIR, BASE_OUTPUT_DUPLICATED_DIR,
    LEAN_APP_ID, LEAN_MASTER_KEY,
    HASH_SALT, HASH_MIN_LENGTH
)

# 爬虫图片路径
SOURCE_SITE = "https://www.pexels.com"
SOURCE_SITE_NAME = 'pexels'
DOWNLOAD_DIR = os.path.join(BASE_OUTPUT_DIR, SOURCE_SITE_NAME)
SOURCE_SITE_DUPLICATED = os.path.join(BASE_OUTPUT_DUPLICATED_DIR, SOURCE_SITE_NAME)

START_PAGE = 1;
CRAWL_BASE_URL = "https://www.pexels.com/popular-photos.js?page="

hashids = Hashids(salt=HASH_SALT, min_length=HASH_MIN_LENGTH)

# 弃用了，现在改成执行 aria2c 命令下载了
def downloadImg(url, name):
    print "name=%s, url=%s" % (name, url)
    path = "./%s" % name
    if os.path.exists(path):
       return
    headers = {'User-Agent':'Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/37.0.2049.0 Safari/537.36'}
    req = urllib2.Request(url, headers=headers)
    data = urllib2.urlopen(req).read()
    f = file(path, "wb")
    f.write(data)
    f.close()

def parsePage(page):
    current_page = CRAWL_BASE_URL + str(page)
    print '\n[Page] %s' % current_page
    content = requests.get(current_page).text
    content = content.replace("\\n", "").replace("\\", "")
    content = content[content.find('<article'):content.find(');')-1]

    soup = BeautifulSoup(content, 'html.parser')
    items = soup.findAll('img')
    
    if len(items) == 0:
        print "[Done] All images downloaded!"
        sys.exit()

    for item in items:
        downloadUrl = item['src'].replace('-medium.', '.')
        imageName = downloadUrl[downloadUrl.rfind('/')+1:]
        if not os.path.isfile(imageName):
            print '[Download] %s' % downloadUrl
            os.system('aria2c -o %s "%s"' % (imageName, downloadUrl));
        else:
            print '[Exist] %s' % imageName
    time.sleep(1.0)
    
    # 检查磁盘空间是否充足，小于 1G 时停止爬取
    vfs = os.statvfs("/Users")
    available = vfs[statvfs.F_BAVAIL]*vfs[statvfs.F_BSIZE]/(1024*1024*1024)
    if available > 1:
        # Parse the next page
        parsePage(page + 1)
    else:
        print 'Disk capacity is not enough, ends at page %d' % page

if __name__ == "__main__":
    if not os.path.exists(DOWNLOAD_DIR): 
        os.mkdir(DOWNLOAD_DIR, 0755)
    os.chdir(DOWNLOAD_DIR)
    parsePage(START_PAGE)


