"""Snap2Map Beijing: screenshot -> addresses -> Amap geocoding -> commute ranking."""
import os
from html import escape
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium
import re
from math import sin, cos, sqrt, pi

st.set_page_config(page_title='Snap2Map 北京选址', page_icon='📍', layout='wide')
st.title('📍 Snap2Map · 北京选址（ChatGPT 粘贴版）')
st.caption('ChatGPT 识别截图 → 粘贴地点 → 高德定位 → 北京通勤比较（测试版）')

COLUMNS = ['name','address','availability']

def amap(endpoint, params, key):
    r = requests.get('https://restapi.amap.com/v3/' + endpoint,
                     params={**params, 'key': key}, timeout=20)
    r.raise_for_status()
    data = r.json()
    if str(data.get('status')) != '1':
        raise ValueError(data.get('info', '高德接口请求失败'))
    return data

def geocode(query, key):
    data = amap('geocode/geo', {'address':query,'city':'北京'},key)
    options = data.get('geocodes', [])
    if not options: return None
    item = options[0]
    lon,lat = map(float,item['location'].split(','))
    return lon,lat,item.get('formatted_address',''),item.get('level','')

def parse_places(text):
    """Accept tab-separated ChatGPT output, or numbered lines with | separators."""
    rows=[]
    for raw in text.splitlines():
        line=raw.strip()
        if not line or line.startswith('```') or line.startswith('#'): continue
        if line.lower().replace(' ','').startswith(('名称','地点名称','name')): continue
        line=re.sub(r'^\s*(?:\d+[.、)）]|[-*•])\s*','',line)
        if '\t' in line: parts=[p.strip() for p in line.split('\t')]
        elif '|' in line: parts=[p.strip() for p in line.strip('|').split('|')]
        else: parts=[line]
        parts=[p for p in parts if p]
        if not parts or (len(parts)>1 and all(set(p)<=set('-: ') for p in parts)): continue
        name=parts[0].strip()
        if not name or name in ('地点','地点名称','名称'): continue
        address=parts[1] if len(parts)>1 else ''
        availability=parts[2] if len(parts)>2 else '未知'
        if availability not in ('可预约','预约已满','未知'): availability='未知'
        rows.append({'name':name,'address':address,'availability':availability})
    return pd.DataFrame(rows,columns=COLUMNS).drop_duplicates(subset=['name','address']).reset_index(drop=True)

# Amap geocodes use GCJ-02; Leaflet/OpenStreetMap uses WGS84.
def gcj_to_wgs(lon,lat):
    def transform_lat(x,y):
        z=-100+2*x+3*y+0.2*y*y+0.1*x*y+0.2*sqrt(abs(x))
        z+=(20*sin(6*x*pi)+20*sin(2*x*pi))*2/3
        z+=(20*sin(y*pi)+40*sin(y*pi/3))*2/3
        return z+(160*sin(y*pi/12)+320*sin(y*pi/30))*2/3
    def transform_lon(x,y):
        z=300+x+2*y+0.1*x*x+0.1*x*y+0.1*sqrt(abs(x))
        z+=(20*sin(6*x*pi)+20*sin(2*x*pi))*2/3
        z+=(20*sin(x*pi)+40*sin(x*pi/3))*2/3
        return z+(150*sin(x*pi/12)+300*sin(x*pi/30))*2/3
    a=6378245.0; ee=0.00669342162296594323
    x=lon-105; y=lat-35
    rad=lat*pi/180; magic=1-ee*sin(rad)**2; root=sqrt(magic)
    dlat=transform_lat(x,y)*180/((a*(1-ee))/(magic*root)*pi)
    dlon=transform_lon(x,y)*180/(a/root*cos(rad)*pi)
    return lon-dlon,lat-dlat

with st.sidebar:
    st.header('地图服务')
    try:
        secret_key = st.secrets.get('AMAP_API_KEY', '')
    except (FileNotFoundError, KeyError):
        secret_key = ''
    amap_key = secret_key or os.getenv('AMAP_API_KEY', '')
    if amap_key:
        st.success('高德地图已连接，可以直接使用')
    else:
        amap_key = st.text_input('高德 Web 服务 API Key', type='password')
    st.caption('截图由 ChatGPT 识别，本网站无需 OpenAI API Key。')

if 'places_df' not in st.session_state:
    st.session_state.places_df=pd.DataFrame(columns=COLUMNS)
if 'mapped' not in st.session_state:
    st.session_state.mapped=None

st.subheader('① 从 ChatGPT 粘贴地点')
st.write('将截图发给 ChatGPT，请它输出每行「地点名称、地址、预约状态」，用 Tab 分隔，然后复制到下方。')
st.caption('以下仅为输入格式示例，请替换成你自己的地点：')
st.code('北京大学\t北京市海淀区颐和园路5号\t可预约', language='text')
pasted = st.text_area('粘贴地点列表（每行一个地点）', height=150,
                      placeholder='北京大学\t北京市海淀区颐和园路5号\t可预约')
if st.button('导入粘贴的地点', type='primary'):
    parsed = parse_places(pasted)
    if parsed.empty:
        st.error('没有识别到地点，请检查是否每行一个地点。')
    else:
        st.session_state.places_df = parsed
        st.session_state.mapped = None
        st.session_state.pop('places_editor', None)
        st.success(f'已导入 {len(parsed)} 个地点。')

st.subheader('② 核对地点和地址')
st.caption(f'当前已导入 {len(st.session_state.places_df)} 个地点。需要修改时点击下方展开。')
with st.expander('展开核对 / 编辑全部地点', expanded=False):
    places = st.data_editor(
        st.session_state.places_df, num_rows='dynamic', hide_index=True,
        key='places_editor', use_container_width=True,
        column_config={
            'name': st.column_config.TextColumn('地点名称', required=True),
            'address': st.column_config.TextColumn('地址'),
            'availability': st.column_config.SelectboxColumn(
                '是否可预约', options=['可预约', '预约已满', '未知'])
        }
    )
    st.caption('修改名称、地址、预约状态，或添加、删除地点；生成地图时自动采用当前表格内容。')
# Expander 收起后编辑结果仍然参与地图计算。
if 'places_editor' not in st.session_state:
    places = st.session_state.places_df.copy()

origin=st.text_input('③ 输入出发地（北京地址、地铁站或学校）',placeholder='例如：北京市海淀区五道口地铁站')
mode=st.selectbox('排序方式',['公共交通时间','驾车时间','直线距离'])
exclude_full=st.checkbox('排名中排除预约已满考点',value=True)

if st.button('④ 高德定位并计算通勤',type='primary'):
    if not amap_key: st.error('请先填写高德 Web 服务 API Key。')
    elif places.empty: st.error('请先添加地点。')
    else:
        try:
            with st.spinner('正在查询地点坐标和通勤时间...'):
                start=geocode('北京市'+origin,amap_key) if origin.strip() else None
                if origin.strip() and start is None: st.warning('出发地未匹配，暂不计算通勤。')
                rows=[]
                for _,r in places.iterrows():
                    name=str(r.get('name','')).strip()
                    if not name: continue
                    address=str(r.get('address','')).strip()
                    row={'name':name,'address':address,'availability':r.get('availability','未知'),
                         'longitude':None,'latitude':None,'matched_address':'','precision':'',
                         'commute_min':None,'distance_km':None,'note':''}
                    try:
                        hit=geocode('北京市'+(address or name),amap_key)
                        if hit is None and address: hit=geocode('北京市'+name,amap_key)
                        if hit:
                            lon,lat,matched,level=hit
                            row.update(longitude=lon,latitude=lat,matched_address=matched,precision=level)
                            if start:
                                from math import radians,sin,cos,asin,sqrt
                                olon,olat=start[:2]
                                aa=sin(radians(lat-olat)/2)**2+cos(radians(olat))*cos(radians(lat))*sin(radians(lon-olon)/2)**2
                                row['distance_km']=round(6371*2*asin(sqrt(aa)),2)
                                if mode=='驾车时间':
                                    data=amap('direction/driving',{'origin':f'{olon},{olat}','destination':f'{lon},{lat}','strategy':0},amap_key)
                                    paths=data.get('route',{}).get('paths',[])
                                    if paths: row['commute_min']=round(float(paths[0]['duration'])/60)
                                elif mode=='公共交通时间':
                                    data=amap('direction/transit/integrated',{'origin':f'{olon},{olat}','destination':f'{lon},{lat}','city':'北京','cityd':'北京','strategy':0},amap_key)
                                    transits=data.get('route',{}).get('transits',[])
                                    durations=[float(t['duration']) for t in transits if t.get('duration')]
                                    if durations: row['commute_min']=round(min(durations)/60)
                        else: row['note']='未找到坐标，请修改地址'
                    except Exception as e: row['note']=str(e)[:100]
                    rows.append(row)
                st.session_state.mapped=pd.DataFrame(rows)
                st.session_state.origin_point=start
        except Exception as e: st.error(f'请求失败：{e}')

if st.session_state.mapped is not None:
    all_df = st.session_state.mapped.copy()
    st.subheader('⑤ 地点地图')
    valid = all_df.dropna(subset=['latitude', 'longitude'])
    if not valid.empty:
        m = folium.Map(location=[39.90, 116.40], zoom_start=10, control_scale=True)
        bounds = []
        for _, r in valid.iterrows():
            lon, lat = gcj_to_wgs(float(r.longitude), float(r.latitude))
            bounds.append([lat, lon])
            status = str(r.availability)
            link = 'https://uri.amap.com/search?keyword=' + quote(str(r['name'])) + '&city=北京'
            content = (f'<b>{escape(str(r["name"]))}</b><br>'
                       f'{escape(str(r["address"]))}<br>{escape(status)}<br>'
                       f'<a href="{link}" target="_blank">高德搜索核对</a>')
            folium.Marker(
                [lat, lon], tooltip=str(r['name']),
                popup=folium.Popup(content, max_width=320),
                icon=folium.Icon(color='red' if status == '预约已满' else 'blue')
            ).add_to(m)
        origin_point = st.session_state.get('origin_point')
        if origin_point:
            olon, olat = gcj_to_wgs(*origin_point[:2])
            folium.Marker([olat, olon], tooltip='出发地',
                          icon=folium.Icon(color='green')).add_to(m)
            bounds.append([olat, olon])
        if len(bounds) > 1:
            m.fit_bounds(bounds, padding=(20, 20))
        st_folium(m, height=460, width=None, returned_objects=[], key='beijing_map')
        st.caption('蓝色：可预约 / 未知；红色：预约已满；绿色：出发地。地图坐标为近似转换，请以高德导航核对。')
        st.download_button('下载交互式 HTML 地图', m.get_root().render().encode('utf-8'),
                           'beijing_map.html', 'text/html')
    else:
        st.warning('尚无有效坐标，无法显示地图。请核对地点地址和 API Key。')

    st.subheader('⑥ 推荐排名')
    df = all_df.copy()
    if exclude_full:
        df = df[df.availability != '预约已满']
    sort_col = 'distance_km' if mode == '直线距离' else 'commute_min'
    # 不把没有有效排序数据的地点错误地推荐为最优。
    ranked = df.dropna(subset=[sort_col]).sort_values([sort_col, 'name'])
    if not origin.strip():
        st.info('请输入出发地并重新计算，才能得到最优地点推荐。')
    elif ranked.empty:
        st.warning('没有可用的通勤或距离数据，暂时无法推荐最优地点。请检查接口返回结果。')
    else:
        def show_place_card(r, rank=None):
            with st.container(border=True):
                title = str(r['name'])
                st.markdown(f'**{str(rank) + ". " if rank is not None else ""}{escape(title)}**')
                commute = '暂无数据' if pd.isna(r['commute_min']) else f'{r["commute_min"]:g} 分钟'
                distance = '暂无数据' if pd.isna(r['distance_km']) else f'{r["distance_km"]:g} 公里'
                st.write(f'通勤时间：{commute}  ·  直线距离：{distance}')
                st.write(f'是否可预约：{r["availability"]}')

        st.caption(f'当前按「{mode}」排序，默认仅展示第一名。')
        show_place_card(ranked.iloc[0], 1)
        if len(ranked) > 1:
            with st.expander(f'展开全部推荐地点（共 {len(ranked)} 个）', expanded=False):
                for i, (_, row) in enumerate(ranked.iloc[1:].iterrows(), start=2):
                    show_place_card(row, i)
    unresolved = all_df[all_df['note'].fillna('').astype(str).ne('')]
    if not unresolved.empty:
        with st.expander(f'查看定位异常地点（{len(unresolved)} 个）', expanded=False):
            for _, row in unresolved.iterrows():
                st.write(f'{row["name"]}：{row["note"]}')
    st.download_button('下载全部选址比较 CSV', all_df.to_csv(index=False).encode('utf-8-sig'),
                       'beijing_venues.csv', 'text/csv')
    st.caption('高德结果可能匹配到街道或区域而非精确考点；通勤时间是估算值，不代表考试当天实时交通。')
