## Caching proxy server

#### Requirements:
`Python`

### Usage:

```
python cache_proxy.py --backend "https://api.github.com"
```

### Options: 
- `--port` sets port number to use
- `--backend` sets the url to cache
- `--cache-dir` sets cache directory
- `--ttl` sets the Time-To-Live
- `--clear` clears saved cache

### Example

Run: 
```
python cache_proxy.py --backend "https://api.github.com"
```

And in another terminal:
```
curl -v "http://localhost:3000/users/octocat"
```

The cache proxy server will forward this request to github and return the response.

![Screenshot From 2025-04-06 11-33-40](https://github.com/user-attachments/assets/d7dbd00f-1108-4f7d-82df-ece80316c0d2)


Send same request again (within 5 mins) and this time you'll receive a cached response as denoted by the `Cache-Status` header.

![Screenshot From 2025-04-06 11-33-54](https://github.com/user-attachments/assets/74c265d5-7ee0-4173-8d06-63d25263aef0)




Part of this challenge: https://roadmap.sh/projects/caching-server
