#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import os
import time
import json
import eth_abi
import requests
import traceback

from web3 import Web3

# Default DEBUG_MODE if not defined elsewhere
DEBUG_MODE = False

class colors:
    INFO = '\033[94m'
    OK = '\033[92m'
    FAIL = '\033[91m'
    WARNING = '\033[93m'
    END = '\033[0m'

def get_events_hash(w3,params):
    trx_hash = params['trx_hash']
    topics = params['topics']
    try:
        receipt = w3.eth.get_transaction_receipt(trx_hash)
        updated_events = list()
        for event in receipt['logs']:
            updated_event = dict(event)
            updated_event["blockHash"] = updated_event["blockHash"].hex()
            updated_event["transactionHash"] = updated_event["transactionHash"].hex()
            for i in range(len(updated_event["topics"])):
                updated_event["topics"][i] = updated_event["topics"][i].hex()
            if updated_event['topics'][0] in topics:
                updated_events.append(updated_event)
        return updated_events

    except Exception as e:
            print(colors.FAIL+"Error: "+str(e)+colors.END)
            return None

def get_events(w3, client_version, params, provider, network="ethereum", session=None):
    if ("geth" in client_version.lower() and network not in ["optimism", "base"]) or network == "arbitrum":
        try:
            events = w3.eth.filter(params).get_all_entries()
            updated_events = list()
            for event in events:
                updated_event = dict(event)
                updated_event["blockHash"] = updated_event["blockHash"].hex()
                updated_event["transactionHash"] = updated_event["transactionHash"].hex()
                for i in range(len(updated_event["topics"])):
                    updated_event["topics"][i] = updated_event["topics"][i].hex()
                updated_events.append(updated_event)
            return updated_events
        except Exception as e:
            error_str = str(e)
            # Don't print common RPC errors that are expected
            if "filter not found" in error_str.lower() or "-32000" in error_str:
                return []
            print(colors.FAIL+"Error: "+error_str+colors.END)
            return []
    elif (network == "ethereum" and "geth" not in client_version.lower()) or network == "optimism" or network == "base" or network == "zksync":
        if session == None:
            session = requests.Session()
        try:
            res = session.post(provider.endpoint_uri, json={
                "jsonrpc": "2.0",
                "method": "eth_getLogs",
                "params": [
                    {
                        "fromBlock": hex(params["fromBlock"]),
                        "toBlock": hex(params["toBlock"]),
                        "topics": params["topics"],
                    }
                ],
                "id": 1
            })
            if res.status_code == 200:
                try:
                    response_json = res.json()
                except Exception as json_error:
                    # If JSON parsing fails, check if response text contains error info
                    response_text = str(res.text) if hasattr(res, 'text') else str(res.content)
                    if "filter not found" in response_text.lower() or "-32000" in response_text:
                        return []
                    return []
                # Check if there's an error in the response
                if "error" in response_json:
                    error_msg = response_json["error"]
                    # Some errors like "filter not found" are expected for certain RPC nodes
                    # Don't print them as they're too verbose - just return empty list
                    if error_msg.get("code") == -32000 and "filter not found" in str(error_msg.get("message", "")):
                        # This is a common RPC error, just return empty list silently
                        return []
                    # For other errors, only print if they're not common RPC issues
                    error_code = error_msg.get("code", 0)
                    error_message = str(error_msg.get("message", ""))
                    # Skip common RPC errors that don't need to be shown
                    if error_code not in [-32000, -32602, -32603] or "rate limit" not in error_message.lower():
                        # Only print non-common errors
                        pass  # Don't print to reduce noise
                    return []
                if "result" in response_json:
                    events = response_json["result"]
                    if events is None:
                        return []
                    for event in events:
                        event["address"] =  w3.to_checksum_address(event["address"].lower())
                        event["blockNumber"] = int(event["blockNumber"], 16)
                        event["transactionIndex"] = int(event["transactionIndex"], 16)
                        event["logIndex"] = int(event["logIndex"], 16)
                        # Process topics - remove 0x prefix
                        for i in range(len(event["topics"])):
                            if event["topics"][i].startswith("0x"):
                                event["topics"][i] = event["topics"][i][2:]
                    return events
                return []
            else:
                # Check if response text contains common RPC errors
                response_text = str(res.text) if hasattr(res, 'text') else ""
                if "filter not found" not in response_text.lower() and "-32000" not in response_text:
                    if DEBUG_MODE:
                        print(colors.FAIL+"Error: Could not retrieve events: "+str(res.status_code)+" "+response_text+" "+str(provider.endpoint_uri)+colors.END)
                return []
        except Exception as e:
            error_str = str(e)
            # Don't print common RPC errors that are expected
            if "filter not found" in error_str.lower() or "-32000" in error_str:
                return []
            # Only print traceback for unexpected errors
            if "DEBUG" in os.environ or False:  # Set to True for debugging
                print(colors.FAIL+str(traceback.format_exc())+colors.END)
                print(colors.FAIL+"Error: "+error_str+colors.END)
            return []
    else:
        print(colors.FAIL+"Error: Client/Network is not supported! Supported clients are Geth and Erigon! Supported networks are Ethereum, Optimism, Base, Arbitrum, and zkSync! Client version: "+client_version+colors.END)
        return None

def get_coin_list(platform, update_prices=False):
    path = os.path.dirname(__file__)
    if update_prices or not os.path.exists(path+"/coin_list_"+platform+".json"):
        print("Getting list of coins from "+colors.INFO+"CoinGecko.com..."+colors.END)
        response = requests.get("https://api.coingecko.com/api/v3/coins/list?include_platform=true").json()
        coin_list = dict()
        if "status" in response and "error_code" in response["status"] and response["status"]["error_code"] == 429:
            print(colors.FAIL+"Error: "+str(response["status"]["error_message"])+colors.END)
        else:
            for coin in response:
                if   platform == "ethereum" and "ethereum" in coin["platforms"] and coin["platforms"]["ethereum"]:
                    coin_list[Web3.to_checksum_address(coin["platforms"]["ethereum"].lower())] = coin["id"]
                elif platform == "arbitrum" and "arbitrum-one" in coin["platforms"] and coin["platforms"]["arbitrum-one"]:
                    coin_list[Web3.to_checksum_address(coin["platforms"]["arbitrum-one"].lower())] = coin["id"]
                elif platform == "optimism" and "optimistic-ethereum" in coin["platforms"] and coin["platforms"]["optimistic-ethereum"]:
                    coin_list[Web3.to_checksum_address(coin["platforms"]["optimistic-ethereum"].lower())] = coin["id"]
                elif platform == "base" and "base" in coin["platforms"] and coin["platforms"]["base"]:
                    coin_list[Web3.to_checksum_address(coin["platforms"]["base"].lower())] = coin["id"]
                elif platform == "zksync" and "zksync" in coin["platforms"] and coin["platforms"]["zksync"]:
                    coin_list[Web3.to_checksum_address(coin["platforms"]["zksync"].lower().split('/')[0].split('#')[0])] = coin["id"]
        with open(path+"/coin_list_"+platform+".json", "w") as f:
            json.dump(coin_list, f, indent=2)
    else:
        if os.path.exists(path+"/coin_list_"+platform+".json"):
            with open(path+"/coin_list_"+platform+".json", "r") as f:
                coin_list = json.load(f)
    return coin_list
    
def get_prices(platform, update_prices=False):
    ... # 前面的代码不变
    coin_list = get_coin_list(platform, update_prices)
    print("Fetching latest prices from "+colors.INFO+"CoinGecko.com..."+colors.END)
    # 修改这行：将起始时间改为365天前
    from_timestamp = str(int(time.time()) - (365 * 24 * 60 * 60)) # 当前时间减去365天
    to_timestamp = str(int(time.time()))
    ... # 前面的代码不变
    
    prices = dict()
    path = os.path.dirname(__file__)
    if os.path.exists(path+"/prices_"+platform+".json"):
        with open(path+"/prices_"+platform+".json", "r") as f:
            prices = json.load(f)
    else:
        prices["eth_to_usd"] = requests.get("https://api.coingecko.com/api/v3/coins/ethereum/market_chart/range?vs_currency=usd&from="+from_timestamp+"&to="+to_timestamp).json()["prices"]
    
    counter = 0
    total = 0
    
    if update_prices:
        print("Retrieving prices for "+colors.INFO+str(len(coin_list))+" coin(s)."+colors.END)
        
        # 使用列表来跟踪处理进度
        addresses_to_process = list(coin_list.keys())
        
        # 从上次保存的进度继续（如果有）
        processed_addresses = set(prices.keys()) - {"eth_to_usd"}
        addresses_to_process = [addr for addr in addresses_to_process if addr not in processed_addresses]
        
        index = 0
        while index < len(addresses_to_process):
            address = addresses_to_process[index]
            total = len(processed_addresses) + index + 1
            total_count = len(coin_list)
            
            if address not in prices:
                market_id = coin_list[address]
                print(address, market_id, "("+str(total)+"/"+str(total_count)+")")
                
                retry_count = 0
                max_retries = 3
                success = False
                
                while retry_count < max_retries and not success:
                    try:
                        response = requests.get("https://api.coingecko.com/api/v3/coins/"+market_id+"/market_chart/range?vs_currency=eth&from="+from_timestamp+"&to="+to_timestamp)
                        
                        # 检查响应状态
                        if response.status_code == 200:
                            data = response.json()
                            if "prices" in data:
                                prices[address] = data["prices"]
                                counter += 1
                                success = True
                                
                                # 保存进度
                                if counter % 5 == 0:
                                    with open(path+"/prices_"+platform+".json", "w") as f:
                                        json.dump(prices, f, indent=2)
                                
                                # 避免速率限制
                                time.sleep(2)
                            else:
                                print(colors.WARNING + f"Warning: No prices data for {market_id}. Skipping." + colors.END)
                                success = True  # 标记为成功以跳过重试
                        elif response.status_code == 429:  # 速率限制
                            retry_count += 1
                            wait_time = 30 * retry_count  # 指数退避
                            print(colors.WARNING + f"Rate limited. Waiting {wait_time} seconds before retry {retry_count}/{max_retries}..." + colors.END)
                            time.sleep(wait_time)
                        elif response.status_code == 503:  # 服务不可用
                            retry_count += 1
                            wait_time = 60  # 服务不可用时等待更长时间
                            print(colors.WARNING + f"Service unavailable. Waiting {wait_time} seconds before retry {retry_count}/{max_retries}..." + colors.END)
                            time.sleep(wait_time)
                        else:
                            # 其他错误
                            try:
                                error_data = response.json()
                                error_msg = str(error_data)
                            except:
                                error_msg = response.text
                            print(colors.FAIL + f"Error for {market_id}: Status {response.status_code}, {error_msg}" + colors.END)
                            success = True  # 标记为成功以跳过此代币
                            
                    except Exception as e:
                        retry_count += 1
                        if retry_count < max_retries:
                            wait_time = 10 * retry_count
                            print(colors.WARNING + f"Exception for {market_id}: {str(e)}. Waiting {wait_time} seconds before retry {retry_count}/{max_retries}..." + colors.END)
                            time.sleep(wait_time)
                        else:
                            print(colors.FAIL + f"Failed to get price for {market_id} after {max_retries} retries: {str(e)}" + colors.END)
                            success = True  # 标记为成功以继续下一个
                
                # 如果成功获取价格，移动到下一个地址
                if success:
                    index += 1
                else:
                    # 如果达到最大重试次数仍然失败，也移动到下一个地址
                    print(colors.FAIL + f"Max retries reached for {market_id}. Skipping." + colors.END)
                    index += 1
        
        # 最终保存
        with open(path+"/prices_"+platform+".json", "w") as f:
            json.dump(prices, f, indent=2)
    
    print("Fetched prices for", colors.INFO+str(len(prices)-1)+colors.END, "coins.")  # 减去eth_to_usd
    return prices, coin_list

# Global flag to track if we've already warned about missing timestamps
_timestamp_warning_shown = False

def get_price_from_timestamp(timestamp, prices):
    global _timestamp_warning_shown
    timestamp *= 1000
    one_eth_to_usd = prices[-1][1]
    for index, _ in enumerate(prices):
        if index < len(prices)-1:
            if prices[index][0] <= timestamp and timestamp <= prices[index+1][0]:
                return prices[index][1]
    # Only show warning once to reduce noise
    if not _timestamp_warning_shown:
        print(colors.FAIL+"Warning: Could not find timestamp for some blocks. Using latest price instead."+colors.END)
        print(colors.FAIL+"Note: Set UPDATE_PRICES=True in settings.py to fetch historical prices."+colors.END)
        _timestamp_warning_shown = True
    return one_eth_to_usd

def encode_with_signature(function_signature, args):
    function_selector = Web3.keccak(text=function_signature)[:4]
    selector_text = function_signature[function_signature.find("(") + 1 : function_signature.rfind(")")]
    arg_types = selector_text.split(",")
    encoded_args = eth_abi.encode(arg_types, args)
    return function_selector + encoded_args

def toSigned256(n):
    n = n & 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    return (n ^ 0x8000000000000000000000000000000000000000000000000000000000000000) - 0x8000000000000000000000000000000000000000000000000000000000000000
