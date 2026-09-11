"""
Precompiled and optimized Lua scripts for Redis atomic rate limiting operations.
These scripts guarantee 100% atomicity under heavy multi-process / multi-server concurrency.
"""

TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local data = redis.call('HMGET', key, 'tokens', 'last_updated')
local tokens = tonumber(data[1])
local last_updated = tonumber(data[2])

if tokens == nil then
    tokens = capacity
    last_updated = now
else
    local delta = math.max(0, now - last_updated)
    tokens = math.min(capacity, tokens + delta * refill_rate)
    last_updated = now
end

local allowed = 0
local remaining = 0
local retry_after = 0
local reset_after = 0

if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
else
    allowed = 0
    retry_after = (cost - tokens) / refill_rate
end

remaining = math.max(0, math.floor(tokens))
reset_after = (capacity - tokens) / refill_rate

redis.call('HMSET', key, 'tokens', tokens, 'last_updated', last_updated)
redis.call('EXPIRE', key, math.ceil(ttl))

return {allowed, remaining, tostring(reset_after), tostring(retry_after)}
"""

SLIDING_WINDOW_COUNTER_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local period = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local current_window = math.floor(now / period)
local prev_window = current_window - 1

local curr_key = tostring(current_window)
local prev_key = tostring(prev_window)

local data = redis.call('HMGET', key, curr_key, prev_key)
local curr_count = tonumber(data[1]) or 0
local prev_count = tonumber(data[2]) or 0

local time_into_current = now - (current_window * period)
local prev_weight = math.max(0, (period - time_into_current) / period)

local estimated_count = curr_count + (prev_count * prev_weight)

local allowed = 0
local remaining = 0
local reset_after = period - time_into_current
local retry_after = 0

if estimated_count + cost <= limit then
    redis.call('HINCRBY', key, curr_key, cost)
    -- Expire after 2 periods so old windows are evicted
    redis.call('EXPIRE', key, math.ceil(period * 2))
    allowed = 1
    remaining = math.max(0, math.floor(limit - estimated_count - cost))
    retry_after = 0
else
    allowed = 0
    remaining = 0
    -- Retry estimate based on window progression
    retry_after = math.max(0.1, reset_after * ((estimated_count + cost - limit) / (prev_count + 1)))
    if retry_after > reset_after then
        retry_after = reset_after
    end
end

return {allowed, remaining, tostring(reset_after), tostring(retry_after)}
"""

FIXED_WINDOW_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local cost = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])

local current = redis.call('INCRBY', key, cost)
if current == cost then
    redis.call('EXPIRE', key, math.ceil(ttl))
end

local allowed = 0
local remaining = 0
local retry_after = 0

if current <= limit then
    allowed = 1
    remaining = limit - current
    retry_after = 0
else
    allowed = 0
    remaining = 0
    retry_after = ttl
end

return {allowed, remaining, tostring(ttl), tostring(retry_after)}
"""

LEAKY_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local leak_rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local data = redis.call('HMGET', key, 'water', 'last_leak')
local water = tonumber(data[1])
local last_leak = tonumber(data[2])

if water == nil then
    water = 0
    last_leak = now
else
    local delta = math.max(0, now - last_leak)
    water = math.max(0, water - delta * leak_rate)
    last_leak = now
end

local allowed = 0
local remaining = 0
local retry_after = 0
local reset_after = water / leak_rate

if water + cost <= capacity then
    water = water + cost
    allowed = 1
    remaining = math.max(0, math.floor(capacity - water))
    retry_after = 0
    reset_after = water / leak_rate
else
    allowed = 0
    remaining = 0
    retry_after = (water + cost - capacity) / leak_rate
end

redis.call('HMSET', key, 'water', water, 'last_leak', last_leak)
redis.call('EXPIRE', key, math.ceil(ttl))

return {allowed, remaining, tostring(reset_after), tostring(retry_after)}
"""

