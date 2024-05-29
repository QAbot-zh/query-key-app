from flask import Flask, request, render_template
import requests, re 
import datetime

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    action = request.form['action']
    api_url = request.form['api_url']
    api_key = request.form['api_key']

    if not api_url or not api_key:
        error = "接口地址和密钥不能为空"
        return render_template('index.html', error=error)
    
    # 使用正则表达式移除以 /v1 起始的部分
    base_url = re.sub(r'^/v1.*', '', api_url)
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
        }
    
    if action == '提交查询':
        model_url = f"{base_url}/v1/models"
        response = requests.get(model_url, headers=headers)
        try:
            response_json = response.json()
            support_models = "\n".join([item['id'] for item in response_json['data']])
        except ValueError:
            support_models = 'Invalid JSON response'

        return render_template('index.html', response=support_models)
    elif action == '检查额度':
        # 获取总额度
        quota_url = f"{base_url}/dashboard/billing/subscription"
        response = requests.get(quota_url, headers=headers)
        try:
            response_json = response.json()
            quota_info = response_json.get('hard_limit_usd', 0)
        except ValueError:
            quota_info = 'Invalid JSON response'
        # 获取使用情况
        today = datetime.datetime.now()
        year, month, day = today.year, today.month, today.day
        start_date = f"{year}-{month:02d}-01"
        end_date = f"{year}-{month:02d}-{day}"
        usage_url = f"{base_url}/dashboard/billing/usage?start_date={start_date}&end_date={end_date}"
        response = requests.get(usage_url, headers=headers)
        try:
            response_json = response.json()
            used_info = response_json.get('total_usage', 0)/100
        except ValueError:
            used_info = 'Invalid JSON response'

        try:
            remain_info = quota_info - used_info
            show_info = f"可用额度为: {remain_info:.2f} $ \n\n已用额度为: {used_info:.2f} $ \n\n  总额度为: {quota_info:.2f} $"
        except Exception:
            remain_info = 0
            show_info = "检查额度失败"

        return render_template('index.html', response=show_info)

if __name__ == '__main__':
    app.run(debug=True)
