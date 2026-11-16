local count = redis.call('INCR', KEYS[1])
local window = tonumber(ARGV[1])

if count == 1 then
  redis.call('EXPIRE', KEYS[1], window)
end

local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
  redis.call('EXPIRE', KEYS[1], window)
  ttl = window
end

return {count, ttl}
