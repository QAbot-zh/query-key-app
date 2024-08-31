import requests, re, os
import datetime
from flask import Flask, request, g, render_template, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
import time
import concurrent.futures

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
    model_timeout = int(request.form.get('model_timeout', 10))  # 默认超时时间为10秒
    model_concurrency = int(request.form.get('model_concurrency', 5))  # 默认并发数为5

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
        test_results = {
            "available_chat_models": [],
            "inconsistent_chat_models": [],
            "unavailable_chat_models": [],
            "not_chat_models": []
        }
        try:
            response = requests.get(model_url, headers=headers, timeout=model_timeout)
            response_json = response.json()
            if not model_health_check:
                response_text = ",".join([item['id'] for item in response_json['data']])
            else:
                not_chat_pattern = r'^(dall|mj|midjourney|stable-diffusion|playground|flux|swap_face|tts|whisper|text|emb|luma|vidu|pdf|suno|pika|chirp|domo|runway|cogvideo)'
                waiting_test_models = []
                for item in response_json['data']:
                    model_name = item['id']
                    if re.match(not_chat_pattern, model_name) or any(keyword in model_name for keyword in ["image","audio","video","music","pdf","flux","suno","embed"]):
                        test_results["not_chat_models"].append({
                            "status": "未校验模型",
                            "model_name": model_name,
                            "response_time": "-",
                            "remarks": "非chat模型暂不进行校验\n（image\\audio\\video\music...）"
                        })
                    else:
                        waiting_test_models.append(model_name)
                with concurrent.futures.ThreadPoolExecutor(max_workers=model_concurrency) as executor:
                    future_to_model = {
                        executor.submit(test_one_model, api_url, api_key, model, model_timeout): model 
                        for model in waiting_test_models
                    }
                    for future in concurrent.futures.as_completed(future_to_model):
                        model_name, response = future.result()
                        if (response.status_code == 200 or response.status_code == 201) and "error" not in response.json():
                            output_model = response.json()["model"]
                            if model_name == output_model:
                                test_results["available_chat_models"].append({
                                    "status": "模型一致可用",
                                    "model_name": model_name,
                                    "response_time": f"{response.elapsed.total_seconds():.2f}",
                                    "remarks": "状态良好"
                                })
                            else:
                                test_results["inconsistent_chat_models"].append({
                                    "status": "模型可用但不一致<br>（即返回模型名称与测试模型名称不一致，注意甄别真假或模型重映射）",
                                    "model_name": model_name,
                                    "response_time": f"{response.elapsed.total_seconds():.2f}",
                                    "remarks": f"返回模型名称：{output_model}"
                                })
                        else:
                            test_results["unavailable_chat_models"].append({
                                "status": "模型不可用！！！",
                                "model_name": model_name,
                                "response_time": "-",
                                "remarks": "超时或无响应"
                            })
                return render_template('index.html', test_results=test_results, api_info=api_info, api_url=api_url, api_key=api_key,    api_key_head=api_key_head)
        except:
            response_text = "无法获取模型列表，api 接口可能存在问题"

        return render_template('index.html', response_text=response_text, api_info=api_info, api_url=api_url, api_key=api_key, api_key_head=api_key_head)
    elif action == '检查额度':
        # 获取总额度
        quota_url = f"{base_url}/dashboard/billing/subscription"
        try:
            response = requests.get(quota_url, headers=headers, timeout=model_timeout)
            response_json = response.json()
            quota_info = response_json.get('hard_limit_usd', 0)
        except:
            quota_info = '无法获得额度信息，api 接口可能存在问题'
        # 获取使用情况
        today = datetime.datetime.now()
        year, month, day = today.year, today.month, today.day
        start_date = f"{year}-{month:02d}-01"
        end_date = f"{year}-{month:02d}-{day}"
        usage_url = f"{base_url}/dashboard/billing/usage?start_date={start_date}&end_date={end_date}"
        try:
            response = requests.get(usage_url, headers=headers, timeout=model_timeout)
            response_json = response.json()
            used_info = response_json.get('total_usage', 0)/100
        except:
            used_info =  '无法获得已用额度信息，api 接口可能存在问题'

        try:
            remain_info = quota_info - used_info
        except:
            remain_info = 0

        quota = {
            "available": f"{remain_info:.2f} $",
            "used": f"{used_info:.2f} $",
            "total": f"{quota_info:.2f} $"
        }

        return render_template('index.html', quota=quota, api_info=api_info, api_url=api_url, api_key=api_key, api_key_head=api_key_head)

def test_one_model(api_url, api_key, model_name, model_timeout=10):
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
    try:
        response = requests.post(test_url, headers=headers, json=data, timeout=model_timeout)
    except Exception as e:
        response = requests.Response()  # 创建一个空的 Response 对象
        response.status_code = 500  # 设置状态码为 500，表示服务器错误
        response.reason = str(e)  # 设置错误原因
        response._content = b'{"error": "Model request failed"}'  # 设置响应内容，可以自定义错误信息
    return model_name,response

@app.route('/test_model', methods=['POST'])
def test_model():
    api_url = request.json.get('api_url')
    api_key = request.json.get('api_key')
    model_name = request.json.get('model_name')

    if not api_url or not api_key or not model_name:
        return jsonify({"success": False, "message": "Missing API URL, API Key, or Model Name"}), 400

    tic = time.time()
    model_name,response = test_one_model(api_url, api_key, model_name)
    duration = time.time() - tic

    if response.status_code == 200 or response.status_code == 201:
        return jsonify({"success": True, "message": "测试成功", "response_time": duration})
    else:
        return jsonify({"success": False, "message": response.text}), response.status_code

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.getenv("PORT", default=5000), debug=True)
