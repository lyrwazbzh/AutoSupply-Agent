-- KEYS[1]=inv:{partId}  KEYS[2]=idem:outbound:{requestId}
-- ARGV[1]=quantity
local qty = tonumber(ARGV[1]) or 0
if qty > 0 then
  redis.call('INCRBY', KEYS[1], qty)
end
redis.call('DEL', KEYS[2])
return 1
