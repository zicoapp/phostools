# coding: utf-8

# Parse meta from local images, and save to leancloud with qiniu-link
# Remove the duplicated local images

# 1. Filter the existing photos in LeanCloud
# 2. Delete the duplicated ones
# 3. Link files from qiniu to leancloud (except the main color) with meta info

import leancloud
from PIL import Image
from PIL import ImageFile
import urllib, urllib2, urllib3
from leancloud import Object, Relation
from leancloud import LeanCloudError
from leancloud import File
from leancloud import Query
import requests
from StringIO import StringIO
import time
import operator
import string
import json
import os
import re
import time
from hashids import Hashids
from qiniu import Auth
from qiniu import Auth, set_default, etag, PersistentFop, build_op, op_save, Zone
from qiniu import put_data, put_file, put_stream
from qiniu import BucketManager, build_batch_copy, build_batch_rename, build_batch_move, build_batch_stat, build_batch_delete
from qiniu import urlsafe_base64_encode, urlsafe_base64_decode

from config import (
    QINIU_ACCESS_KEY, QINIU_SECRET_KEY, QINIU_BUCKET, QINIU_BASE_URL,
    LEAN_APP_ID, LEAN_MASTER_KEY,
    BASE_OUTPUT_DIR, BASE_OUTPUT_DUPLICATED_DIR,
    HASH_SALT, HASH_MIN_LENGTH
)

SOURCE_SITE_NAME = 'pexels'
SOURCE_SITE = 'https://www.pexels.com'
SYNC_DIR = os.path.join(BASE_OUTPUT_DIR, SOURCE_SITE_NAME)
SYNC_DIR_DUPLICATED = os.path.join(BASE_OUTPUT_DUPLICATED_DIR, SOURCE_SITE_NAME)

# 初始化 leancloud
leancloud.init(LEAN_APP_ID, master_key=LEAN_MASTER_KEY)

# 创建七牛仓管
q = Auth(QINIU_ACCESS_KEY, QINIU_SECRET_KEY)
bucket = BucketManager(q)

# 有道翻译
youdao = 'http://fanyi.youdao.com/openapi.do?keyfrom=Phoscc&key=1905168548&type=data&doctype=json&version=1.1&q='

# LeanCloud 存储
Photo = Object.extend('Photo')
PhotoTag = Object.extend('PhotoTag')
Tag = Object.extend('Tag')

# Avoid 'image file is truncated' error
ImageFile.LOAD_TRUNCATED_IMAGES = True
hashids = Hashids(salt=HASH_SALT, min_length=HASH_MIN_LENGTH)

# Download image by url
def downloadImg(url, name):
    path = os.path.join(SYNC_DIR, name)
    data = urllib2.urlopen(url).read()
    f = file(path, "wb")
    f.write(data)
    f.close()

# 给图片做差分哈希
def dhash(image, hash_size = 8):
    # Grayscale and shrink the image in one step.
    image = image.convert('L').resize(
        (hash_size + 1, hash_size),
        Image.ANTIALIAS,
    )

    pixels = list(image.getdata())

    # Compare adjacent pixels.
    difference = []
    for row in xrange(hash_size):
        for col in xrange(hash_size):
            pixel_left = image.getpixel((col, row))
            pixel_right = image.getpixel((col + 1, row))
            difference.append(pixel_left > pixel_right)

    # Convert the binary array to a hexadecimal string.
    decimal_value = 0
    hex_string = []
    for index, value in enumerate(difference):
        if value:
            decimal_value += 2**(index % 8)
        if (index % 8) == 7:
            hex_string.append(hex(decimal_value)[2:].rjust(2, '0'))
            decimal_value = 0

    return ''.join(hex_string)


# 将七牛链接保存到 LeanCloud
def savePhoto(meta):
    photo = Photo()
    photo.set('title', meta['title'])
    photo.set('format', meta['format'])
    photo.set('url', meta['url'])
    photo.set('dhash', meta['hashtext'])
    # photo.set('color', meta['color'])
    photo.set('width', meta['width'])
    photo.set('source', meta['source'])
    photo.set('height', meta['height'])
    photo.set('size', meta['size'])
    photo.set('palette', meta['palette'])

    photo.set('released', False)
    photo.save()
    query = Query(Photo)
    avosphoto = query.equal_to('title', meta['title']).first()
    print(meta['title'] + '  >  ' + avosphoto.id)
    return avosphoto

# 通过七牛的在线 API 获取图片主色调
# 注意：这个 API 在照片过大时，会调用失败
def getImageAve(key):
    photo_url = BASE_URL + key + '?imageAve'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.0; WOW64; rv:24.0) Gecko/20100101 Firefox/24.0'}
    r = requests.get(photo_url, headers=headers)
    data = r.json()
    color = data.get('RGB')  
    return color

# 从图片文件中解析 meta 信息
def parseImageMeta(fileName, im):
    meta = {}

    meta['url'] = QINIU_BASE_URL + fileName
    meta['format'] = fileName[fileName.rfind('.')+1 :]
    meta['title'] = fileName
    meta['source'] = SOURCE_SITE

    # 哈希
    hashtext = dhash(im)
    meta['hashtext'] = hashtext

    # 主色调
    # imageAve = getImageAve(key)
    # if imageAve is not None:
    #     meta['color'] = str(imageAve[2:])
    # else:
    #     meta['color'] = ''

    # 尺寸
    meta['width'] = im.width
    meta['height'] = im.height

    # 大小
    meta['size'] = int(round(os.path.getsize(os.path.join(SYNC_DIR, fileName)) / 1000.0))

    # 使用本地库，获取调色板（5中颜色）
    img = im.convert('P', palette=Image.ADAPTIVE, colors=5)
    img.putalpha(0)
    colors = img.getcolors()
    colors = sorted(colors, key=operator.itemgetter(0), reverse=True)
    palette = []
    for icolor in colors:
        percent = round(icolor[0] / (im.width * im.height * 1.0), 2)
        rgb = hex(icolor[1][0])[2:] + hex(icolor[1][1])[2:] + hex(icolor[1][2])[2:]
        rgbitem = (percent, rgb)
        palette.append(rgbitem)
    meta['palette'] = palette

    return meta

# 有道翻译 API 调用
def translate(tags):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.0; WOW64; rv:24.0) Gecko/20100101 Firefox/24.0'}
    tagsout = []
    tagsout.extend(tags)
    for tag in tags:
        r = requests.get(youdao + tag, headers=headers)
        data = json.loads(r.text, encoding='utf-8')
        trans = data['translation']
        for chinesetag in trans:
            tagsout.append(chinesetag.encode('utf-8'))
    for t in tagsout: print t,
    print ''
    return tagsout
   
# 给照片打标签
def tagphoto(avosPhoto, tags):
    for tagtext in tags:
        tagquery = Query(Tag)
        tagquery.equal_to('name', tagtext)
        remoteTags = tagquery.find()
        avosTag = Tag()
        if len(tagquery.find()) == 0:
            avosTag.set('name', tagtext)
            avosTag.set('count', 1)
        else:
            avosTag = remoteTags[0]
            avosTag.increment('count', 1) 
        avosTag.save()
        ptag = PhotoTag()
        ptag.set('tag', avosTag)
        ptag.save()
        
        avosPhoto = Photo()
        ptagrelation = avosPhoto.relation('ptags')
        ptagrelation.add(ptag)
        avosPhoto.save()
        

# 将本地文件信息同步到 LeanCloud, list_qiuniu 失败的文件
def sync_local():
    files = [ f for f in os.listdir(SYNC_DIR) if os.path.isfile(os.path.join(SYNC_DIR, f)) ]
    for f in files:
        fileName = f
        filePath = os.path.join(SYNC_DIR, f)
        if not (fileName.endswith('.jpeg') or fileName.endswith('.png') or fileName.endswith('.jpeg')):
            continue

        print('\n' + filePath)
        
        # 计算照片模糊 Hash 值
        im = Image.open(filePath)
        hash_meta = dhash(im)
        
        # 查询 LeanCloud，从本地移除重复照片
        query = Query(Photo)
        query.equal_to('dhash', hash_meta)
        results = query.find()
        if len(results) != 0:
            print "duplicate: (local=%s, leancloud=%s)" % (fileName, results[0].get('url'))
            os.rename(filePath, os.path.join(SYNC_DIR_DUPLICATED, fileName))
            continue

        # keep original file name for use in case
        originFileName = fileName

        millis = int(round(time.time() * 1000))
        hashFileName = hashids.encode(millis) + fileName[fileName.rfind('.')+1 :]
        os.rename(filePath, os.path.join(SYNC_DIR, hashFileName))

        # 解析 meta 信息
       	meta = parseImageMeta(hashFileName, im)
        # 保存链接与 meta 到 LeanCloud
        avosPhoto = savePhoto(meta)

        # 标签翻译，一些网站的文件下载名，是又若干标签组成的，这里将其分开翻译，并添加到该照片的标签字段中
        # titletags = originFileName[:originFileName.index('.')].split('-')
        # if len(titletags) > 2:
        #     tags = translate(titletags)
        #     tagphoto(avosPhoto, tags) 

if __name__ == '__main__':
    # Create download directory
    if not os.path.exists(SYNC_DIR): 
        os.mkdir(SYNC_DIR, 0755)
    # Where duplicated images put
    if not os.path.exists(SYNC_DIR_DUPLICATED): 
        os.mkdir(SYNC_DIR_DUPLICATED, 0755)
    # List local image, and sync
    sync_local()
