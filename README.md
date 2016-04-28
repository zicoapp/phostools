# PHOS_TOOLS

## 目前图片图库流程

以 pexels.com 站点为例

- 执行 pexels.py，爬取 XXX 站点图片到本地(服务器)。就是普通的解析，提取链接下载保存。下载直接用了 aria2c 命令

- 执行 sync_new.py，将本地爬取的图片信息同步到 Leancloud 数据库

```
1. 遍历待同步的图片
2. 计算图片 Hash 值 (模糊值，可以匹配微小差异)
3. 查询 Leancloud 判断该 hash 对应的照片是否存在，若存在则移至 duplicated 目录，回到 1
4. 取当前时间获得 hash 字符串，重名名当前图片文件名
5. 解析当前图片的 meta 信息，width/height/size/palette/hash 等，且记该照片在七牛的路径为 qiniu_repo_url/xxxx.xxx (此时并不存在与七牛服务器)
6. 保存 meta 信息到 leancloud
```

- 执行 ./qrsync sync.json，将本地图片上传到七牛服务器

---

步骤比较分散，其实蛮容易出错的，然后手动修复==
