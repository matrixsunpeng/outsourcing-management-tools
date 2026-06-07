"""
主流程 - 根据人员面试评价表自动新签
1. 查询飞书多维表中"是否签署"为否的记录
2. 按三字段组合分组
3. 逐组在 IMS 完成外包合同新签
4. 签署结果回写多维表

用法:
  python main.py        # 逐条交互确认
  python main.py -y     # 自动确认提交（跳过交互）
"""

import os
import sys
from datetime import datetime
from dotenv import dotenv_values

# 禁用输出缓冲，容忍编码错误
sys.stdout.reconfigure(line_buffering=True, errors='replace')

from playwright.sync_api import sync_playwright

from ims_login import create_browser_context, login_ims
from ims_contract import navigate_to_contract_page, process_contract_group
from feishu_query import query_unsigned_records, group_records_by_contract, get_bitable_config


def main():
    # 解析命令行参数
    auto_yes = "-y" in sys.argv or "--yes" in sys.argv

    print("=" * 60)
    print(f"根据人员面试评价表自动新签 - 开始运行 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if auto_yes:
        print("模式: 自动确认提交")
    else:
        print("模式: 交互确认（每条询问是否提交）")
    print("=" * 60)

    # 加载配置
    config_path = os.path.join(os.path.dirname(__file__), "config.env")
    config = dotenv_values(config_path)

    username = config.get("IMS_USERNAME", "")
    password = config.get("IMS_PASSWORD", "")

    if not username or not password:
        print("[ERROR] 请先在 config.env 中填写 IMS_USERNAME 和 IMS_PASSWORD")
        sys.exit(1)

    # Step 1: 查询多维表未签署记录
    print("\n[Step 1] 查询飞书多维表未签署记录")
    unsigned_records = query_unsigned_records(config_path)

    if not unsigned_records:
        print("\n没有未签署的记录，流程结束")
        return

    print(f"\n共找到 {len(unsigned_records)} 条未签署记录")

    # Step 2: 按三字段组合分组
    print("\n[Step 2] 按组合字段分组")
    groups = group_records_by_contract(unsigned_records)

    if not groups:
        print("\n没有有效的合同组合，流程结束")
        return

    print(f"\n共 {len(groups)} 个合同组合待处理")

    # Step 3: 启动浏览器并登录 IMS
    print("\n[Step 3] 登录 IMS 网站")
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)

    bitable_token, table_id = get_bitable_config(config_path)

    with sync_playwright() as p:
        browser, context, page = create_browser_context(p, data_dir)

        try:
            page = login_ims(page, username, password)

            # Step 4: 导航到外包合同页面
            print("\n[Step 4] 导航到外包合同页面")
            contract_page = navigate_to_contract_page(page)

            # Step 5: 逐组处理
            success_count = 0
            skip_count = 0
            fail_count = 0

            for idx, group in enumerate(groups):
                app_code = group["application_code"]
                signing_party = group["signing_party"]
                supplier = group["supplier"]
                person_count = len(group["personnel"])

                print(f"\n[Group {idx + 1}/{len(groups)}] {app_code} ({person_count} person(s))")
                print("-" * 50)

                try:
                    # 后续组需要重新导航到外包合同页面
                    if idx > 0:
                        print("  重新导航到外包合同页面...")
                        contract_page = navigate_to_contract_page(page)

                    # 处理当前合同组合
                    result = process_contract_group(
                        contract_page, group,
                        auto_yes=auto_yes,
                        bitable_token=bitable_token,
                        table_id=table_id,
                    )

                    status = result["status"]
                    if status == "SUCCESS":
                        success_count += 1
                        print(f"  [OK] 组合 {app_code} 签署成功")
                    elif status == "SKIPPED":
                        skip_count += 1
                        print(f"  [SKIP] 组合 {app_code} 用户跳过")
                    else:
                        fail_count += 1
                        print(f"  [FAIL] 组合 {app_code} 签署失败: {result.get('reason', '未知')}")

                except Exception as e:
                    fail_count += 1
                    print(f"  [ERROR] 组合 {app_code} 处理异常: {e}")
                    import traceback
                    traceback.print_exc()

                # 组间清理：确保所有弹窗关闭
                for i in range(3):
                    page.evaluate("""(function(){
                        var wins=document.querySelectorAll('.mini-window,.mini-modal,.mini-messagebox');
                        for(var i=0;i<wins.length;i++){
                            try{
                                var w=wins[i];
                                if(w.offsetParent!==null){
                                    var c=w.querySelector('.mini-tools-close,.mini-panel-tools-close');
                                    if(c) c.click();
                                    var id=w.id||w.getAttribute('id')||'';
                                    if(id&&window.mini){var ctrl=mini.get(id);if(ctrl&&ctrl.destroy)ctrl.destroy();}
                                    // 找确定按钮点击关闭
                                    var btns=w.querySelectorAll('a,button,span');
                                    for(var j=0;j<btns.length;j++){
                                        var t=(btns[j].innerText||'').trim();
                                        if(t==='确定'||t==='OK'){btns[j].click();break;}
                                    }
                                }
                            }catch(e){}
                        }
                        document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',keyCode:27,bubbles:true}));
                    })()""")
                    page.wait_for_timeout(500)
                contract_page.wait_for_timeout(2000)

            # 最终报告
            print("\n" + "=" * 60)
            print("执行完成！")
            print(f"  - 未签署记录: {len(unsigned_records)} 条")
            print(f"  - 合同组合数: {len(groups)} 个")
            print(f"  - 签署成功: {success_count} 个")
            print(f"  - 用户跳过: {skip_count} 个")
            print(f"  - 签署失败: {fail_count} 个")
            print("=" * 60)

        except Exception as e:
            print(f"\n[ERROR] 执行异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
