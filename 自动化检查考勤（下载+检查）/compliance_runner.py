"""
合规检查包装器
从原始 check_compliance.py 提取核心检查逻辑，封装为可调用的函数，供 GUI 使用。
原始脚本位置: F:\\ClaudeCode\\学习检查考勤\\check_compliance.py
"""
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import calendar
import os
import glob
import re
import warnings
warnings.filterwarnings('ignore')


# ===== 公共函数 =====
def find_files(folder, keyword):
    """按关键字在文件夹中查找Excel文件"""
    pattern_xlsx = os.path.join(folder, f"*{keyword}*.xlsx")
    pattern_xls = os.path.join(folder, f"*{keyword}*.xls")
    files = sorted(glob.glob(pattern_xlsx) + glob.glob(pattern_xls))
    files = [f for f in files if not os.path.basename(f).startswith('~')]
    return files

def get_workdays_in_month(year, month):
    num_days = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, num_days + 1) if date(year, month, d).weekday() < 5]


# ===== 数据加载 =====
def load_all_data(base_dir, target_year, target_month_num, exclude_sbu, log_func=None):
    """
    加载所有数据文件，返回各数据DataFrame。
    log_func: 可选的日志回调函数 log_func(message)
    """
    def log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    workdays = get_workdays_in_month(target_year, target_month_num)
    month_start = date(target_year, target_month_num, 1)
    month_end = date(target_year, target_month_num, calendar.monthrange(target_year, target_month_num)[1])
    log(f"工作日数量: {len(workdays)} ({workdays[0]} ~ {workdays[-1]})")

    target_month_str = f"{target_year}{target_month_num:02d}"

    # --- 1. 在岗人员清单 ---
    log("\n===== 1. 在岗人员清单 =====")
    staff_files = find_files(base_dir, "在岗人员清单")
    if not staff_files:
        raise FileNotFoundError("未找到在岗人员清单文件")

    df_staff_list = []
    for f in staff_files:
        df_preview = pd.read_excel(f, header=None, nrows=3)
        header_row = 1 if len(df_preview) > 1 else 0
        row0_text = str(df_preview.iloc[0].values[0]) if len(df_preview) > 0 else ''
        if '变化表' in row0_text or '清单' in row0_text or '统计' in row0_text:
            header_row = 1
        df = pd.read_excel(f, header=header_row)
        df_staff_list.append(df)
        log(f"  {os.path.basename(f)}: {len(df)}行")
    df_staff_all = pd.concat(df_staff_list, ignore_index=True)

    df_staff_all['工作开始时间'] = pd.to_datetime(df_staff_all['工作开始时间'], errors='coerce')
    df_staff_all['工作结束时间'] = pd.to_datetime(df_staff_all['工作结束时间'], errors='coerce')
    df_staff_all_month = df_staff_all[
        (df_staff_all['工作开始时间'].dt.date <= month_end) &
        (df_staff_all['工作结束时间'].dt.date >= month_start)
    ].copy()

    if exclude_sbu:
        df_staff_all_month = df_staff_all_month[
            ~df_staff_all_month['SBU'].astype(str).str.contains(exclude_sbu, na=False)
        ]
    log(f"  月份筛选+排除SBU后: {len(df_staff_all_month)}人")

    # --- 2. 工时详细查询 ---
    log("\n===== 2. 工时详细查询 =====")
    workhour_files = find_files(base_dir, "工时详细查询")
    df_workhour_month = pd.DataFrame()
    if workhour_files:
        df_wh_list = []
        for f in workhour_files:
            df_preview = pd.read_excel(f, header=None, nrows=3)
            row0_text = str(df_preview.iloc[0].values[0]) if len(df_preview) > 0 else ''
            header_row = 1 if ('查询' in row0_text or '详细' in row0_text or '统计' in row0_text) else 0
            df = pd.read_excel(f, header=header_row)
            df_wh_list.append(df)
            log(f"  {os.path.basename(f)}: {len(df)}行")
        df_workhour = pd.concat(df_wh_list, ignore_index=True)
        df_workhour['考勤日期'] = pd.to_datetime(df_workhour['考勤日期'], errors='coerce')
        df_workhour_month = df_workhour[
            (df_workhour['考勤日期'].dt.year == target_year) &
            (df_workhour['考勤日期'].dt.month == target_month_num)
        ].copy()
        df_workhour_month['身份证号_str'] = df_workhour_month['身份证号'].astype(str).str.strip()
    else:
        log("  警告: 未找到工时详细查询文件")

    # --- 3. 场地签 ---
    log("\n===== 3. 场地签 =====")
    sign_files = find_files(base_dir, "场地签")
    df_sign_month = pd.DataFrame()
    if sign_files:
        df_sign_list = []
        for f in sign_files:
            df = pd.read_excel(f, header=0)
            if '签到日期' in df.columns and '日期' not in df.columns:
                df.rename(columns={'签到日期': '日期'}, inplace=True)
            df_sign_list.append(df)
            log(f"  {os.path.basename(f)}: {len(df)}行")
        df_sign = pd.concat(df_sign_list, ignore_index=True)
        df_sign['日期'] = pd.to_datetime(df_sign['日期'], errors='coerce')
        df_sign_month = df_sign[
            (df_sign['日期'].dt.year == target_year) & (df_sign['日期'].dt.month == target_month_num)
        ].copy()
        df_sign_month['员工工号_str'] = df_sign_month['员工工号'].astype(str).str.strip()
        df_sign_month['员工姓名_str'] = df_sign_month['员工姓名'].astype(str).str.strip()
    else:
        log("  警告: 未找到场地签文件")

    # --- 4. 差旅 ---
    log("\n===== 4. 差旅 =====")
    travel_files = find_files(base_dir, "差旅")
    df_travel_month = pd.DataFrame()
    if travel_files:
        df_travel_list = []
        for f in travel_files:
            df = pd.read_excel(f, header=0)
            df_travel_list.append(df)
            log(f"  {os.path.basename(f)}: {len(df)}行")
        df_travel = pd.concat(df_travel_list, ignore_index=True)
        df_travel['行程开始时间'] = pd.to_datetime(df_travel['行程开始时间'], errors='coerce')
        df_travel['行程结束时间'] = pd.to_datetime(df_travel['行程结束时间'], errors='coerce')
        df_travel_month = df_travel[
            (df_travel['行程开始时间'].dt.date <= month_end) &
            (df_travel['行程结束时间'].dt.date >= month_start)
        ].copy()
        df_travel_month['出行人工号_str'] = df_travel_month['出行人工号'].astype(str).str.strip()
        df_travel_month['出行人姓名_str'] = df_travel_month['出行人姓名'].astype(str).str.strip()
    else:
        log("  警告: 未找到差旅文件")

    # --- 5. 计提报表 ---
    log("\n===== 5. 计提报表 =====")
    accrual_files = find_files(base_dir, "计提报表")
    df_accrual_month = pd.DataFrame()
    if accrual_files:
        df_acc_list = []
        for f in accrual_files:
            df_preview = pd.read_excel(f, header=None, nrows=3)
            row0_text = str(df_preview.iloc[0].values[0]) if len(df_preview) > 0 else ''
            header_row = 1 if ('报表' in row0_text or '计提' in row0_text or '结算' in row0_text) else 0
            df = pd.read_excel(f, header=header_row)
            df_acc_list.append(df)
            log(f"  {os.path.basename(f)}: {len(df)}行")
        df_accrual = pd.concat(df_acc_list, ignore_index=True)
        df_accrual['本期结算月份_str'] = df_accrual['本期结算月份'].astype(str).str.strip()
        df_accrual_month = df_accrual[df_accrual['本期结算月份_str'] == target_month_str].copy()
        df_accrual_month['身份证号_str'] = df_accrual_month['身份证号'].astype(str).str.strip()
    else:
        log("  警告: 未找到计提报表文件")

    return {
        'workdays': workdays,
        'month_start': month_start,
        'month_end': month_end,
        'target_month_str': target_month_str,
        'df_staff_all_month': df_staff_all_month,
        'df_workhour_month': df_workhour_month,
        'df_sign_month': df_sign_month,
        'df_travel_month': df_travel_month,
        'df_accrual_month': df_accrual_month,
    }


# ===== 合规检查函数 =====
def run_compliance_check(supplier_keyword, data, log_func=None):
    """
    对指定供应商执行合规检查，返回 (non_compliant_list, reason_stats)。
    data: load_all_data 返回的数据字典
    """
    def log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    df_staff_all_month = data['df_staff_all_month']
    df_workhour_month = data['df_workhour_month']
    df_sign_month = data['df_sign_month']
    df_travel_month = data['df_travel_month']
    df_accrual_month = data['df_accrual_month']
    workdays = data['workdays']
    month_start = data['month_start']
    month_end = data['month_end']

    log(f"\n{'─' * 50}")
    log(f"  正在检查供应商: {supplier_keyword}")
    log(f"{'─' * 50}")

    # --- 筛选该供应商的人员 ---
    df_staff = df_staff_all_month[
        df_staff_all_month['合作商'].astype(str).str.contains(supplier_keyword, na=False, case=False)
    ].copy()
    log(f"  匹配供应商: {len(df_staff)}人")

    staff_id_list = df_staff['身份证号'].dropna().unique().tolist()
    staff_info = {}
    staff_empno = {}
    for _, row in df_staff.iterrows():
        id_num = str(row['身份证号']).strip()
        empno = str(row.get('工号', '')).strip()
        if empno and empno != 'nan':
            staff_empno[empno] = id_num
        if id_num not in staff_info:
            staff_info[id_num] = {
                'SBU': row['SBU'], '姓名': row['姓名'], '身份证号': id_num,
                '工号': empno, '工作地': row['工作地'], '合作商': row['合作商'],
                '工作开始时间': row['工作开始时间'], '工作结束时间': row['工作结束时间'],
            }
        else:
            existing = staff_info[id_num]
            if pd.notna(row['工作开始时间']) and (pd.isna(existing['工作开始时间']) or row['工作开始时间'] < existing['工作开始时间']):
                existing['工作开始时间'] = row['工作开始时间']
            if pd.notna(row['工作结束时间']) and (pd.isna(existing['工作结束时间']) or row['工作结束时间'] > existing['工作结束时间']):
                existing['工作结束时间'] = row['工作结束时间']
    log(f"  待检查人员: {len(staff_info)}人")

    if len(staff_info) == 0:
        log("  该供应商无匹配人员，跳过")
        return [], {}

    name_to_ids = {}
    for id_num, info in staff_info.items():
        name = str(info['姓名']).strip()
        if name not in name_to_ids:
            name_to_ids[name] = []
        name_to_ids[name].append(id_num)

    person_workhour = df_workhour_month[df_workhour_month['身份证号_str'].isin(staff_id_list)] if len(df_workhour_month) > 0 else pd.DataFrame()

    # --- 场地签匹配 ---
    def get_id_from_sign(row):
        empno = row['员工工号_str']
        if empno in staff_empno:
            return staff_empno[empno]
        name = row['员工姓名_str']
        if name in name_to_ids and len(name_to_ids[name]) == 1:
            return name_to_ids[name][0]
        return None

    sign_matched = pd.DataFrame()
    if len(df_sign_month) > 0:
        sign_pool = df_sign_month[
            df_sign_month['员工工号_str'].isin(staff_empno.keys()) |
            df_sign_month['员工姓名_str'].isin(name_to_ids.keys())
        ].copy()
        if len(sign_pool) > 0:
            sign_pool['身份证号_matched'] = sign_pool.apply(get_id_from_sign, axis=1)
            sign_matched = sign_pool[sign_pool['身份证号_matched'].notna()]
    log(f"  场地签匹配: {len(sign_matched)}条")

    # --- 差旅日期展开 ---
    def get_id_from_travel(row):
        empno = row['出行人工号_str']
        if empno in staff_empno:
            return staff_empno[empno]
        name = row['出行人姓名_str']
        if name in name_to_ids and len(name_to_ids[name]) == 1:
            return name_to_ids[name][0]
        return None

    travel_dates_v2 = {}
    if len(df_travel_month) > 0:
        travel_pool = df_travel_month[
            df_travel_month['出行人工号_str'].isin(staff_empno.keys()) |
            df_travel_month['出行人姓名_str'].isin(name_to_ids.keys())
        ].copy()
        if len(travel_pool) > 0:
            travel_pool['身份证号_matched'] = travel_pool.apply(get_id_from_travel, axis=1)
            travel_matched = travel_pool[travel_pool['身份证号_matched'].notna()]
            for _, row in travel_matched.iterrows():
                id_num = row['身份证号_matched']
                if id_num not in travel_dates_v2:
                    travel_dates_v2[id_num] = set()
                start = row['行程开始时间']
                end = row['行程结束时间']
                dest = str(row['目的地']).strip() if pd.notna(row['目的地']) else ''
                if pd.notna(start) and pd.notna(end):
                    start_d = start.date() if isinstance(start, pd.Timestamp) else start
                    end_d = end.date() if isinstance(end, pd.Timestamp) else end
                    start_d = max(start_d, month_start)
                    end_d = min(end_d, month_end)
                    current = start_d
                    while current <= end_d:
                        travel_dates_v2[id_num].add((current, dest))
                        current += timedelta(days=1)

    # --- 计提报表 ---
    accrual_info = {}
    if len(df_accrual_month) > 0:
        acc_pool = df_accrual_month[df_accrual_month['身份证号_str'].isin(staff_id_list)]
        for _, row in acc_pool.iterrows():
            id_num = row['身份证号_str']
            subtotal = row.get('小计(实际费用+月考核费)', 0)
            try:
                subtotal = float(subtotal) if pd.notna(subtotal) else 0
            except:
                subtotal = 0
            if id_num not in accrual_info:
                accrual_info[id_num] = {'subtotal': subtotal}
            else:
                accrual_info[id_num]['subtotal'] += subtotal

    # ===== 逐人合规检查 =====
    non_compliant = []
    for id_num, info in staff_info.items():
        name = info['姓名']
        sbu = str(info['SBU']).strip()
        work_city = str(info['工作地']).strip()
        supplier = str(info['合作商']).strip()
        reasons = []

        ws = info['工作开始时间']
        we = info['工作结束时间']
        ws_d = ws.date() if pd.notna(ws) else (ws if isinstance(ws, date) else month_start)
        we_d = we.date() if pd.notna(we) else (we if isinstance(we, date) else month_end)
        actual_start = max(ws_d, month_start)
        actual_end = min(we_d, month_end)
        person_workdays = [d for d in workdays if actual_start <= d <= actual_end]

        person_wh = person_workhour[person_workhour['身份证号_str'] == id_num] if len(person_workhour) > 0 else pd.DataFrame()

        leave_dates = set()
        for _, wh_row in person_wh.iterrows():
            att_date = wh_row['考勤日期']
            att_type = str(wh_row['考勤类型']).strip() if pd.notna(wh_row['考勤类型']) else ''
            if pd.notna(att_date) and '请假' in att_type:
                att_d = att_date.date() if isinstance(att_date, pd.Timestamp) else att_date
                leave_dates.add(att_d)

        # ---- 条件1: 签到合规 ----
        person_sign = sign_matched[sign_matched['身份证号_matched'] == id_num] if len(sign_matched) > 0 else pd.DataFrame()
        sign_dates = set()
        sign_cities = {}
        is_workhour_person = True

        for _, s_row in person_sign.iterrows():
            s_date = s_row['日期']
            s_status = str(s_row.get('签到状态', '')).strip() if pd.notna(s_row.get('签到状态', '')) else ''
            if pd.notna(s_date) and s_status != '未签到':
                s_d = s_date.date() if isinstance(s_date, pd.Timestamp) else s_date
                sign_dates.add(s_d)
                s_city = str(s_row['签到城市']).strip() if pd.notna(s_row['签到城市']) else ''
                if s_city:
                    sign_cities[s_d] = s_city
            is_wh = str(s_row.get('是否工时人员', '是')).strip()
            if is_wh == '否':
                is_workhour_person = False

        if not is_workhour_person and len(person_sign) > 0:
            pass
        else:
            required_sign_days = [d for d in person_workdays if d not in leave_dates]
            missing_sign_days = [d for d in required_sign_days if d not in sign_dates]
            if len(missing_sign_days) > 3:
                reasons.append(f"签到缺失: {len(missing_sign_days)}个工作日未签到(超过3天), 缺失日期: {', '.join(str(d) for d in missing_sign_days)}")

        # ---- 条件2: 签到城市匹配 ----
        person_travel = travel_dates_v2.get(id_num, set())
        travel_date_set = set(d for d, _ in person_travel)

        leave_date_set = set()
        for _, wh_row in person_wh.iterrows():
            att_type = str(wh_row['考勤类型']).strip() if pd.notna(wh_row['考勤类型']) else ''
            if '请假' in att_type and pd.notna(wh_row['考勤日期']):
                att_d = wh_row['考勤日期'].date() if isinstance(wh_row['考勤日期'], pd.Timestamp) else wh_row['考勤日期']
                leave_date_set.add(att_d)

        city_mismatch = []
        for s_d, s_city in sign_cities.items():
            if s_d not in set(person_workdays):
                continue
            work_city_clean = work_city.replace('市', '').strip()
            sign_city_clean = s_city.replace('市', '').strip()
            if work_city_clean != sign_city_clean and work_city != s_city:
                if s_d not in travel_date_set and s_d not in leave_date_set:
                    city_mismatch.append(f"{s_d}(工作地:{work_city}, 签到:{s_city})")
        if len(city_mismatch) > 3:
            reasons.append(f"签到城市不匹配: {len(city_mismatch)}天城市不一致(超过3天), {', '.join(city_mismatch)}")

        # ---- 条件3: 工时状态合规 ----
        status_issues = 0
        for _, wh_row in person_wh.iterrows():
            is_workday = str(wh_row['是否工作日']).strip() if pd.notna(wh_row['是否工作日']) else ''
            status = str(wh_row['状态']).strip() if pd.notna(wh_row['状态']) else ''
            att_type = str(wh_row['考勤类型']).strip() if pd.notna(wh_row['考勤类型']) else ''
            if is_workday == '是' and '请假' not in att_type:
                if status != '项目经理审批通过':
                    status_issues += 1
        if status_issues > 3:
            reasons.append(f"工时状态不合规: {status_issues}个工作日状态非'项目经理审批通过'(超过3天)")

        # ---- 条件4: 请假合规 ----
        leave_workdays = 0
        non_exempt_leave_days = 0
        non_exempt_leave_types = set()
        allowed_types = {'产假', '病假', '婚假', '陪产假'}
        for _, wh_row in person_wh.iterrows():
            is_workday = str(wh_row['是否工作日']).strip() if pd.notna(wh_row['是否工作日']) else ''
            att_type = str(wh_row['考勤类型']).strip() if pd.notna(wh_row['考勤类型']) else ''
            leave_type = str(wh_row['请假类型']).strip() if pd.notna(wh_row['请假类型']) else ''
            if is_workday == '是' and '请假' in att_type:
                leave_workdays += 1
                if leave_type in allowed_types:
                    pass
                else:
                    non_exempt_leave_days += 1
                    if leave_type:
                        non_exempt_leave_types.add(leave_type)
        if non_exempt_leave_days > 3:
            reasons.append(f"请假超期: {leave_workdays}个工作日请假, 其中非豁免类型{non_exempt_leave_days}天(超过3天), 非豁免类型: {', '.join(non_exempt_leave_types)}")

        # ---- 条件5: 计提报表 ----
        acc = accrual_info.get(id_num, None)
        if acc is None or acc['subtotal'] <= 0:
            reasons.append("计提报表缺失或小计为0")

        # ---- 条件6: 项目编号 ----
        if is_workhour_person and len(person_wh) > 0:
            proj_col = None
            for col_candidate in ['项目编号', '项目编码']:
                if col_candidate in person_wh.columns:
                    proj_col = col_candidate
                    break
            if proj_col:
                total_workdays = 0
                non_empty_proj_days = 0
                for _, wh_row in person_wh.iterrows():
                    is_workday = str(wh_row['是否工作日']).strip() if pd.notna(wh_row['是否工作日']) else ''
                    if is_workday == '是':
                        total_workdays += 1
                        proj_code = str(wh_row[proj_col]).strip() if pd.notna(wh_row[proj_col]) else ''
                        if proj_code != '' and proj_code != 'nan':
                            non_empty_proj_days += 1
                if total_workdays > 0 and non_empty_proj_days == 0:
                    reasons.append(f"项目编号全为空: {total_workdays}个工作日工时均缺少项目编号")

        if reasons:
            non_compliant.append({
                'SBU': sbu, '姓名': name, '身份证号': id_num, '工号': info['工号'],
                '工作地': work_city, '合作商': supplier,
                '工作开始时间': info['工作开始时间'], '工作结束时间': info['工作结束时间'],
                '不合规原因': '; '.join(reasons),
            })

    reason_stats = {'签到缺失': 0, '签到城市不匹配': 0, '工时状态不合规': 0, '请假超期': 0, '计提报表缺失': 0, '项目编号全为空': 0}
    for item in non_compliant:
        r = item['不合规原因']
        for k in reason_stats:
            if k in r:
                reason_stats[k] += 1

    log(f"  检查完成: {len(staff_info)}人, 合规{len(staff_info) - len(non_compliant)}人, 不合规{len(non_compliant)}人")
    return non_compliant, reason_stats


# ===== 完整执行流程 =====
def run_full_check(month_str, supplier_list, base_dir, output_dir=None, exclude_sbu="AIS", log_func=None, stop_event=None):
    """
    完整执行合规检查流程。
    参数:
        month_str: 月份字符串，如 "202604"
        supplier_list: 供应商名称列表
        base_dir: 数据文件夹路径
        output_dir: 输出文件夹路径（默认同 base_dir）
        exclude_sbu: 排除的SBU关键字
        log_func: 日志回调函数
    返回:
        dict: {supplier_name: (non_compliant_list, reason_stats)}
    """
    def log(msg):
        if log_func:
            log_func(msg)
        else:
            print(msg)

    if output_dir is None:
        output_dir = base_dir

    # 解析月份
    target_year = int(month_str[:4])
    target_month_num = int(month_str[4:6])
    target_month = f"{target_year}年{target_month_num}月"

    log(f"{'=' * 50}")
    log(f"  考勤合规检查")
    log(f"{'=' * 50}")
    log(f"  检查月份: {target_month}")
    log(f"  供应商: {', '.join(supplier_list)}")
    log(f"  数据文件夹: {base_dir}")
    log(f"  输出文件夹: {output_dir}")
    log(f"  排除SBU: {exclude_sbu}")
    log(f"{'=' * 50}\n")

    # 加载数据
    data = load_all_data(base_dir, target_year, target_month_num, exclude_sbu, log_func)

    # 逐供应商检查
    all_results = {}
    for supplier in supplier_list:
        if stop_event and stop_event.is_set():
            log("[中断] 合规检查已被用户停止")
            break
        nc, stats = run_compliance_check(supplier, data, log_func)
        all_results[supplier] = (nc, stats)

        if nc:
            df_result = pd.DataFrame(nc)
            output_filename = f"{target_month}_{supplier}_考勤合规检查表.xlsx"
            output_path = os.path.join(output_dir, output_filename)

            with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                df_result.to_excel(writer, index=False, sheet_name='不合规人员')
                ws = writer.sheets['不合规人员']
                for col, width in {'A': 20, 'B': 10, 'C': 22, 'D': 12, 'E': 10, 'F': 30, 'G': 15, 'H': 15, 'I': 80}.items():
                    ws.column_dimensions[col].width = width
            log(f"  输出文件: {output_path}")
        elif len(nc) == 0 and stats is not None and len(stats) > 0:
            log(f"  该供应商所有人员均合规，不生成文件")

    # 汇总
    log(f"\n{'=' * 50}")
    log(f"  检查汇总")
    log(f"{'=' * 50}")
    for supplier, (nc, stats) in all_results.items():
        log(f"\n  【{supplier}】 不合规: {len(nc)}人")
        if stats:
            for k, v in stats.items():
                if v > 0:
                    log(f"    {k}: {v}人")
    log(f"\n{'=' * 50}")
    log("检查全部完成！")

    return all_results
