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

SAMPLE = [
 ('北方工业大学','晋元庄路5号','可预约'),('国家林业和草原局管理干部学院','林校北路8号','可预约'),
 ('ATA国际认证中心（北京北清路）','北清路103号中科产业园1B楼','可预约'),('北京市黄庄职业高中','鲁谷东街29号','可预约'),
 ('北京市商业学校（昌平校区）','曹八西路28号','可预约'),('北京市海淀区金科培训学校','亮甲店130号华玉大厦二层','可预约'),
 ('中国传媒大学','定福庄东街1号','可预约'),('北京信息职业技术学院（南区）','花乡辛庄90号','可预约'),
 ('北京市仪器仪表高级技工学校（西城校区）','西什库大街31号','可预约'),('首钢工学院（南门入校）','晋元庄路6号','可预约'),
 ('中国石油大学润杰公寓','东环路148号润杰公寓','可预约'),('首都医科大学花乡校区','花乡张家路口107号','可预约'),
 ('潘家园街道社区综合体（原创享空间）','潘家园华威北里23号楼东侧','可预约'),('北京开放大学东城分校','东四西大街48号','可预约'),
 ('首都师范大学信息工程学院','西三环北路56号','预约已满'),('向导教学中心','羊坊店东路5号博望园底商二层','可预约')]
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
    st.header('API 设置')
 
    amap_key = st.secrets.get("AMAP_API_KEY", "")

    if amap_key:
        st.success("高德地图已连接，可以直接使用")
    else:
        amap_key = st.text_input(
            "高德 Web 服务 API Key",
            type="password"
        )
    st.caption('ChatGPT 负责识别截图：此版本无需 OpenAI API Key。请勿公开高德 Key。')

if 'places_df' not in st.session_state:
    st.session_state.places_df=pd.DataFrame(columns=COLUMNS)
if 'mapped' not in st.session_state:
    st.session_state.mapped=None

st.subheader('① 从 ChatGPT 粘贴地点')
st.write('把截图发给 ChatGPT，让它输出每行「地点名称、地址、预约状态」三列，用 Tab 分隔。复制到下面的文本框。')
st.code('北方工业大学\t晋元庄路5号\t可预约\n首都师范大学信息工程学院\t西三环北路56号\t预约已满',language='text')
pasted=st.text_area('粘贴地点列表（每行一个地点）',height=165,placeholder='北方工业大学\t晋元庄路5号\t可预约')
left,right=st.columns(2)
with left:
    if st.button('导入粘贴的地点',type='primary'):
        parsed=parse_places(pasted)
        if parsed.empty: st.error('没有识别到地点。请检查是否每行一个地点。')
        else:
            st.session_state.places_df=parsed
            st.session_state.mapped=None
            st.success(f'已导入 {len(parsed)} 个地点。')
with right:
    if st.button('载入之前截图中的 16 个北京考点（示例）'):
        st.session_state.places_df=pd.DataFrame(SAMPLE,columns=COLUMNS)
        st.session_state.mapped=None

st.subheader('② 核对地点和地址')
places=st.data_editor(st.session_state.places_df,num_rows='dynamic',hide_index=True,
                      key='places_editor',use_container_width=True)
st.caption('可直接修改错误名称或地址，也可新增、删除考点。定位前请检查校区和楼栋信息。')
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
    df=st.session_state.mapped.copy()
    st.subheader('⑤ 结果和推荐排名')
    st.warning('高德返回的是候选地理编码结果，街道级或区域级匹配可能不准确。请检查匹配地址；通勤时间是接口估算值，不代表考试当天实时路况。')
    if exclude_full: df=df[df.availability!='预约已满']
    sort='distance_km' if mode=='直线距离' else 'commute_min'
    df=df.sort_values([sort,'name'],na_position='last')
    st.dataframe(df[['name','address','availability','commute_min','distance_km','matched_address','precision','note']],hide_index=True,use_container_width=True)
    valid=st.session_state.mapped.dropna(subset=['latitude','longitude'])
    if not valid.empty:
        m=folium.Map(location=[valid.latitude.mean(),valid.longitude.mean()],zoom_start=11,control_scale=True)
        bounds=[]
        for _,r in valid.iterrows():
            lat_gcj,lon_gcj=float(r.latitude),float(r.longitude)
            lon,lat=gcj_to_wgs(lon_gcj,lat_gcj)
            bounds.append([lat,lon])
            status=str(r.availability)
            link='https://uri.amap.com/search?keyword='+quote(str(r['name']))+'&city=北京'
            content=f'<b>{escape(str(r["name"]))}</b><br>{escape(str(r["address"]))}<br>{escape(status)}<br><a href="{link}" target="_blank">高德搜索核对</a>'
            folium.Marker([lat,lon],tooltip=str(r['name']),popup=folium.Popup(content,max_width=320),
                          icon=folium.Icon(color='red' if status=='预约已满' else 'blue')).add_to(m)
        origin_point=st.session_state.get('origin_point')
        if origin_point:
            olon,olat=gcj_to_wgs(*origin_point[:2])
            folium.Marker([olat,olon],tooltip='出发地',icon=folium.Icon(color='green')).add_to(m)
            bounds.append([olat,olon])
        if len(bounds)>1: m.fit_bounds(bounds,padding=(20,20))
        st_folium(m,height=540,width=None,returned_objects=[])
        st.caption('地图使用 OpenStreetMap 底图，并对高德 GCJ-02 坐标进行近似 WGS84 转换。结果仅供选址参考，具体位置与路线请在高德地图核对。')
        st.download_button('下载选址比较 CSV',df.to_csv(index=False).encode('utf-8-sig'),'beijing_venues.csv','text/csv')
        st.download_button('下载交互式 HTML 地图',m.get_root().render().encode('utf-8'),'beijing_map.html','text/html')
    else: st.error('尚无可显示的有效坐标。')
