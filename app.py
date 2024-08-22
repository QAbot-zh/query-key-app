import requests, re, os
import datetime
from flask import Flask, request, g, render_template, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
import time

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    api_url_lazy, api_key_lazy = None,None
    api_info = request.form.get('api_info')
    api_key_head = request.form.get('api_key_head')
    model_health_check = request.form.get('model_health_check') == 'on'

    if api_info:
        # 使用正则表达式提取接口地址和API密钥
        url_pattern = r'(https?://[^\s，。、！,；;\n]+)'
        api_key_head = api_key_head or "sk-"
        key_pattern = fr'({re.escape(api_key_head)}[a-zA-Z0-9_]+)'

        api_url_match = re.search(url_pattern, api_info)
        api_key_match = re.search(key_pattern, api_info)

        if api_url_match and api_key_match:
            api_url_lazy = api_url_match.group(0)
            api_key_lazy = api_key_match.group(0)

    action = request.form['action']
    api_url = request.form['api_url']
    api_key = request.form['api_key']

    if not api_url or not api_key:
        if not api_url_lazy or not api_key_lazy:
            error = "未提取到正确的接口地址和密钥"
            return render_template('index.html', error=error)
        else:
            api_url, api_key = api_url_lazy, api_key_lazy
    
    # 使用正则表达式移除以 /v1 起始的部分
    base_url = re.sub(r'^/v1.*', '', api_url)
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
        }
    
    if action == '拉取模型列表':
        model_url = f"{base_url}/v1/models"
        response = requests.get(model_url, headers=headers)
        try:
            response_json = response.json()
            if not model_health_check:
                support_models = "支持的模型列表：\n\n" + "\n".join([item['id'] for item in response_json['data']])
            else:
                available_chat_models,unavailable_chat_models,not_chat_models = [],[],[]
                not_chat_pattern = r'^(dall-e|mj|midjourney|stable-diffusion|playground|flux|swap_face|tts-|whisper-|text-|emb-)'
                for item in response_json['data']:
                    model_name = item['id']
                    if re.match(not_chat_pattern, model_name) or ("flux" in model_name):
                        not_chat_models.append(model_name)
                    else:
                        response = test_one_model(api_url, api_key, model_name)
                        if response.status_code == 200 or response.status_code == 201:
                            available_chat_models.append(model_name)
                        else:
                            unavailable_chat_models.append(model_name)
                support_models = "已校验可用chat模型：\n" + "\n".join(available_chat_models) + "\n\n" + "已校验不可用chat模型：\n" + "\n".join(unavailable_chat_models) + "\n\n" + "未校验模型（不对非chat模型进行校验）：\n" + "\n".join(not_chat_models)
        except:
            support_models = response.text

        return render_template('index.html', response=support_models, api_info=api_info, api_url=api_url, api_key=api_key, api_key_head=api_key_head)
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

        return render_template('index.html', response=show_info, api_info=api_info, api_url=api_url, api_key=api_key, api_key_head=api_key_head)

def test_one_model(api_url, api_key, model_name):
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    test_url = f"{api_url}/v1/chat/completions"
    data = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": "say hi"}
        ],
        "max_tokens": 2
    }
    response = requests.post(test_url, headers=headers, json=data)
    return response

@app.route('/test_model', methods=['POST'])
def test_model():
    api_url = request.json.get('api_url')
    api_key = request.json.get('api_key')
    model_name = request.json.get('model_name')

    if not api_url or not api_key or not model_name:
        return jsonify({"success": False, "message": "Missing API URL, API Key, or Model Name"}), 400

    tic = time.time()
    response = test_one_model(api_url, api_key, model_name)
    duration = time.time() - tic

    if response.status_code == 200 or response.status_code == 201:
        return jsonify({"success": True, "message": "测试成功", "response_time": duration})
    else:
        return jsonify({"success": False, "message": response.text}), response.status_code

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.getenv("PORT", default=5000), debug=True)
