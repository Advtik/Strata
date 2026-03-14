from fastapi import FastAPI, Request, Response
import httpx 
app=FastAPI()


@app.api_route("/proxy/{full_path:path}",methods=["GET","POST","PUT","PATCH","DELETE"])
async def root(full_path:str,request:Request):
    query_params=request.query_params
    baseURL="https://postman-echo.com"
    target_url=f"{baseURL}/{full_path}"
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    headers.pop("connection", None)


    async with httpx.AsyncClient() as client:
        response=await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=query_params,
            content=await request.body()
        )
        excluded = {
            "content-length",
            "transfer-encoding",
            "connection",
            "content-encoding"
        }
        resp_headers={}
        resp_headers = {}

        for k,v in response.headers.items():
            if k.lower() not in excluded:
                resp_headers[k] = v
                
        return Response(content=response.content, status_code=response.status_code, headers=resp_headers)

        

