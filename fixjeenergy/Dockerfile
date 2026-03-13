ARG BUILD_FROM
FROM $BUILD_FROM

ENV LANG C.UTF-8

# Install dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip

# Install Python libraries
RUN pip install --no-cache-dir --break-system-packages \
    aiohttp \
    nordpool \
    pytz \
    fastapi \
    uvicorn \
    jinja2

# Set working directory
WORKDIR /app

# Copy application files
COPY . .
RUN chmod a+x run.sh

CMD [ "./run.sh" ]
