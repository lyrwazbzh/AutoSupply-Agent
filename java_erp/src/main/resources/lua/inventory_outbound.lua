-- KEYS[1]=inv:{partId} 库存量
-- KEYS[2]=idem:outbound:{requestId} 幂等标记
-- ARGV[1]=quantity  ARGV[2]=requestId  ARGV[3]=ttlSeconds
-- 返回: 1=成功扣减  0=库存不足  2=幂等命中已处理  -1=参数非法

local qty = tonumber(ARGV[1])
local requestId = ARGV[2]
local ttl = tonumber(ARGV[3]) or 86400
if (not qty) or qty < 1 then
  return -1
end
if redis.call('EXISTS', KEYS[2]) == 1 then
  return 2
end
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
if cur < qty then
  return 0
end
redis.call('DECRBY', KEYS[1], qty)
redis.call('SET', KEYS[2], requestId, 'EX', ttl)
return 1
