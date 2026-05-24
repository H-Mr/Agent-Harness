# 如何部署到 Kubernetes

本文将指导你如何将 llm-harness Agent 容器化并部署到 Kubernetes 集群。

---

## 前置条件

开始之前，请确保已准备以下环境：

- **Docker** — 用于构建容器镜像
- **kubectl** — Kubernetes 命令行工具，已配置集群访问
- **K8s 集群** — 可用的 Kubernetes 集群（本地 minikube、云服务商 EKS/GKE/ACK 均可）
- **容器镜像仓库** — 可推送镜像的仓库（Docker Hub、GitHub Container Registry、阿里云 ACR 等）

---

## 1. 创建 Dockerfile

在项目根目录创建 `Dockerfile`：

```dockerfile
# ---- build stage ----
FROM python:3.11-slim AS builder

WORKDIR /app

# 安装 uv（更快的包管理器）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 复制依赖清单并安装
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group prod

# ---- runtime stage ----
FROM python:3.11-slim

WORKDIR /app

# 安装运行时系统依赖（用于 shell 工具执行）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 阶段复制已安装的依赖
COPY --from=builder /app/.venv /app/.venv

# 复制项目代码
COPY src/ /app/src/
COPY pyproject.toml /app/

# 设置 PATH 以使用虚拟环境中的 Python
ENV PATH="/app/.venv/bin:$PATH"

# 暴露健康检查端口（用于 K8s liveness/readiness probe）
EXPOSE 8080

# 默认启动命令：单次对话模式
CMD ["oh"]
```

!!! tip "多阶段构建"
    多阶段构建将依赖安装与运行时分离，最终镜像仅包含运行所需的最小文件，显著缩小镜像体积。

使用以下命令构建镜像：

```bash
docker build -t your-registry/llm-harness-agent:latest .
docker push your-registry/llm-harness-agent:latest
```

---

## 2. K8s Deployment 清单

创建一个完整的 Deployment 配置文件 `deployment.yaml`：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llm-harness-agent
  namespace: default
  labels:
    app: llm-harness-agent
spec:
  replicas: 2
  selector:
    matchLabels:
      app: llm-harness-agent
  template:
    metadata:
      labels:
        app: llm-harness-agent
    spec:
      serviceAccountName: llm-harness-agent
      containers:
        - name: agent
          image: your-registry/llm-harness-agent:latest
          imagePullPolicy: Always
          command:
            - "oh"
            - "--mode"
            - "serve"
          env:
            # LLM Provider 配置
            - name: HARNESS_AGENT__API_KEY
              valueFrom:
                secretKeyRef:
                  name: llm-provider
                  key: api-key
            - name: HARNESS_AGENT__MODEL
              value: "claude-sonnet-4-6"
            - name: HARNESS_AGENT__PROVIDER
              value: "anthropic"
            - name: HARNESS_AGENT__WORKSPACE
              value: "/data/workspace"

            # 可观测性
            - name: HARNESS_OBSERVABILITY__TRACK_FILE
              value: "/data/track.jsonl"

          ports:
            - containerPort: 8080
              name: http
              protocol: TCP

          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2"
              memory: "2Gi"

          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 30
            periodSeconds: 15
            timeoutSeconds: 5
            failureThreshold: 3

          readinessProbe:
            httpGet:
              path: /ready
              port: http
            initialDelaySeconds: 10
            periodSeconds: 10
            timeoutSeconds: 3

          volumeMounts:
            - name: workspace-data
              mountPath: /data
            - name: config
              mountPath: /app/config
              readOnly: true

      volumes:
        - name: workspace-data
          persistentVolumeClaim:
            claimName: llm-harness-workspace
        - name: config
          configMap:
            name: llm-harness-config
```

### 必需的环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `HARNESS_AGENT__API_KEY` | LLM Provider API 密钥 | 通过 Secret 注入 |
| `HARNESS_AGENT__MODEL` | 模型名称 | `claude-sonnet-4-6` |
| `HARNESS_AGENT__PROVIDER` | Provider 类型 | `anthropic` / `openai_compat` |
| `HARNESS_AGENT__WORKSPACE` | 工作目录（持久化） | `/data/workspace` |

!!! warning "API 密钥安全"
    永远不要在 YAML 中明文写入 API 密钥。使用 `Secret` 资源并通过 `valueFrom.secretKeyRef` 引用。

---

## 3. K8s Service + Ingress

### Service

创建 `service.yaml` 将 Deployment 暴露为内部服务：

```yaml
apiVersion: v1
kind: Service
metadata:
  name: llm-harness-agent
  namespace: default
  labels:
    app: llm-harness-agent
spec:
  selector:
    app: llm-harness-agent
  ports:
    - name: http
      port: 80
      targetPort: 8080
  type: ClusterIP
```

### Ingress

创建 `ingress.yaml` 对外暴露服务（需要集群中已安装 Ingress Controller）：

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: llm-harness-agent
  namespace: default
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - agent.your-domain.com
      secretName: llm-harness-tls
  rules:
    - host: agent.your-domain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: llm-harness-agent
                port:
                  number: 80
```

---

## 4. 多场景部署：一个 Deployment 对应一个 Agent

当需要运行多个不同角色的 Agent 时（如客服 Agent、代码审查 Agent、数据分析 Agent），每个 Agent 使用独立的 Deployment。

### 场景 1：客服 Agent

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: customer-service-agent
  namespace: default
spec:
  replicas: 3
  selector:
    matchLabels:
      app: customer-service-agent
  template:
    metadata:
      labels:
        app: customer-service-agent
    spec:
      containers:
        - name: agent
          image: your-registry/llm-harness-agent:latest
          command:
            - "oh"
            - "--mode"
            - "serve"
          env:
            - name: HARNESS_AGENT__API_KEY
              valueFrom:
                secretKeyRef:
                  name: llm-provider
                  key: api-key
            - name: HARNESS_AGENT__MODEL
              value: "claude-sonnet-4-6"
            - name: HARNESS_AGENT__WORKSPACE
              value: "/data/workspace"
            # 客服 Agent 特定配置：限制可用工具
            - name: HARNESS_TOOLS__ENABLED_0
              value: "read_file"
            - name: HARNESS_TOOLS__ENABLED_1
              value: "web_search"
            - name: HARNESS_TOOLS__DISABLED_0
              value: "exec"
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "1"
              memory: "1Gi"
```

### 场景 2：自动化 Agent（使用 Cron）

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: automation-agent
  namespace: default
spec:
  replicas: 1
  selector:
    matchLabels:
      app: automation-agent
  template:
    metadata:
      labels:
        app: automation-agent
    spec:
      containers:
        - name: agent
          image: your-registry/llm-harness-agent:latest
          command:
            - "oh"
            - "--mode"
            - "cron"
          env:
            - name: HARNESS_AGENT__API_KEY
              valueFrom:
                secretKeyRef:
                  name: llm-provider
                  key: api-key
            - name: HARNESS_AGENT__MODEL
              value: "gpt-4o"
            - name: HARNESS_AGENT__PROVIDER
              value: "openai_compat"
            - name: HARNESS_AGENT__WORKSPACE
              value: "/data/workspace"
          resources:
            requests:
              cpu: "200m"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "1Gi"
          volumeMounts:
            - name: workspace-data
              mountPath: /data
      volumes:
        - name: workspace-data
          persistentVolumeClaim:
            claimName: automation-workspace
```

---

## 5. 配置与密钥

### ConfigMap：业务配置

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: llm-harness-config
  namespace: default
data:
  settings.json: |
    {
      "agent": {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "max_iterations": 40,
        "temperature": 0.7
      },
      "permission": {
        "mode": "default",
        "denied_tools": ["exec"]
      },
      "tools": {
        "exec_timeout": 60,
        "enabled": ["*"],
        "disabled": []
      },
      "observability": {
        "track_file": "/data/track.jsonl"
      }
    }
```

### Secret：API 密钥

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: llm-provider
  namespace: default
type: Opaque
stringData:
  api-key: "sk-your-api-key-here"
```

!!! danger "不要提交 Secret"
    永远不要将 `stringData` 中的敏感值提交到 Git。使用外部密钥管理工具（如 HashiCorp Vault、阿里云 KMS、AWS Secrets Manager）并结合 Sealed Secrets 或 External Secrets Operator。

### PersistentVolumeClaim：持久化工作目录

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: llm-harness-workspace
  namespace: default
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
```

---

## 6. 滚动更新策略

在 Deployment 中配置滚动更新，实现零宕机更新：

```yaml
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1          # 允许额外启动 1 个 Pod
      maxUnavailable: 0     # 保证最少全部可用
  minReadySeconds: 10
```

更新镜像时，执行：

```bash
kubectl set image deployment/llm-harness-agent agent=your-registry/llm-harness-agent:v2
kubectl rollout status deployment/llm-harness-agent
```

如需回滚：

```bash
kubectl rollout undo deployment/llm-harness-agent
```

---

## 7. 验证部署

### 检查 Pod 状态

```bash
kubectl get pods -l app=llm-harness-agent
```

预期输出：

```
NAME                                   READY   STATUS    RESTARTS   AGE
llm-harness-agent-7d4f8b9c6f-a1b2c    1/1     Running   0          2m
llm-harness-agent-7d4f8b9c6f-d3e4f    1/1     Running   0          2m
```

### 查看日志

```bash
kubectl logs -l app=llm-harness-agent --tail=100
```

### 测试健康检查端点

```bash
# 端口转发到本地
kubectl port-forward svc/llm-harness-agent 8080:80

# 测试健康检查
curl http://localhost:8080/health
curl http://localhost:8080/ready
```

### 验证 Ingress

```bash
curl https://agent.your-domain.com/health
```

### 完整部署脚本

```bash
#!/bin/bash
set -euo pipefail

NAMESPACE="default"

echo "==> 创建 ConfigMap..."
kubectl apply -f configmap.yaml -n "$NAMESPACE"

echo "==> 创建 Secret..."
kubectl apply -f secret.yaml -n "$NAMESPACE"

echo "==> 创建 PVC..."
kubectl apply -f pvc.yaml -n "$NAMESPACE"

echo "==> 部署 Service..."
kubectl apply -f service.yaml -n "$NAMESPACE"

echo "==> 部署 Ingress..."
kubectl apply -f ingress.yaml -n "$NAMESPACE"

echo "==> 部署 Agent..."
kubectl apply -f deployment.yaml -n "$NAMESPACE"

echo "==> 等待 rollout 完成..."
kubectl rollout status deployment/llm-harness-agent -n "$NAMESPACE"

echo "==> 部署完成！"
kubectl get pods -l app=llm-harness-agent -n "$NAMESPACE"
```

---

## 8. 完整 YAML 示例

以下为完整可部署的 `all-in-one.yaml`（生产环境中建议按资源拆分）：

??? example "all-in-one.yaml"
    ```yaml
    ---
    apiVersion: v1
    kind: Namespace
    metadata:
      name: llm-harness
    ---
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: llm-harness-config
      namespace: llm-harness
    data:
      settings.json: |
        {
          "agent": {
            "model": "claude-sonnet-4-6",
            "max_tokens": 4096,
            "max_iterations": 40
          },
          "permission": {
            "mode": "default"
          },
          "observability": {
            "track_file": "/data/track.jsonl"
          }
        }
    ---
    apiVersion: v1
    kind: Secret
    metadata:
      name: llm-provider
      namespace: llm-harness
    type: Opaque
    stringData:
      api-key: "sk-your-api-key"
    ---
    apiVersion: v1
    kind: PersistentVolumeClaim
    metadata:
      name: llm-harness-workspace
      namespace: llm-harness
    spec:
      accessModes:
        - ReadWriteOnce
      resources:
        requests:
          storage: 10Gi
    ---
    apiVersion: v1
    kind: Service
    metadata:
      name: llm-harness-agent
      namespace: llm-harness
    spec:
      selector:
        app: llm-harness-agent
      ports:
        - name: http
          port: 80
          targetPort: 8080
      type: ClusterIP
    ---
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: llm-harness-agent
      namespace: llm-harness
    spec:
      replicas: 2
      strategy:
        type: RollingUpdate
        rollingUpdate:
          maxSurge: 1
          maxUnavailable: 0
      selector:
        matchLabels:
          app: llm-harness-agent
      template:
        metadata:
          labels:
            app: llm-harness-agent
        spec:
          containers:
            - name: agent
              image: your-registry/llm-harness-agent:latest
              imagePullPolicy: Always
              command: ["oh", "--mode", "serve"]
              env:
                - name: HARNESS_AGENT__API_KEY
                  valueFrom:
                    secretKeyRef:
                      name: llm-provider
                      key: api-key
                - name: HARNESS_AGENT__MODEL
                  value: "claude-sonnet-4-6"
                - name: HARNESS_AGENT__WORKSPACE
                  value: "/data/workspace"
                - name: HARNESS_OBSERVABILITY__TRACK_FILE
                  value: "/data/track.jsonl"
              ports:
                - containerPort: 8080
                  name: http
              resources:
                requests:
                  cpu: "500m"
                  memory: "512Mi"
                limits:
                  cpu: "2"
                  memory: "2Gi"
              livenessProbe:
                httpGet:
                  path: /health
                  port: http
                initialDelaySeconds: 30
                periodSeconds: 15
              readinessProbe:
                httpGet:
                  path: /ready
                  port: http
                initialDelaySeconds: 10
                periodSeconds: 10
              volumeMounts:
                - name: workspace-data
                  mountPath: /data
                - name: config
                  mountPath: /app/config
                  readOnly: true
          volumes:
            - name: workspace-data
              persistentVolumeClaim:
                claimName: llm-harness-workspace
            - name: config
              configMap:
                name: llm-harness-config
    ```

---

## 相关参考

- [配置参考](../api/config.md) — 完整的环境变量和配置文件说明
- [观测追踪](enable-observability.md) — 如何开启 JSONL 日志追踪
- [架构设计](../explanation/architecture.md) — llm-harness 整体架构
