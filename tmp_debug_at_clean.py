from app.modules.nba_live_text.zhiboba_livetext import clean_live_text_for_tokenization, LiveTextFilterRule

rules = []
samples = [
    '@萌神哦麦噶：库明加这么打有前途',
    '@爱你得很：艾顿需要球权，中距离其实很柔和',
    '@笑个T：打岀小高潮',
    '@ 玉鼎山人里斯夫：3分钟失误2次',
]
for item in samples:
    print(item, '=>', clean_live_text_for_tokenization(item, rules))
