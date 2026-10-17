{{- define "cs.name" -}}
{{-  .Release.Name | trunc 50 | trimSuffix "-" -}}
{{- end -}}
{{- define "cs.labels" -}}
app.kubernetes.io/name: cloudscope
app.kubernetes.io/instance: {{ .Release.Name | quote }}
{{- end -}}
{{- define "cs.secret" -}}
{{- if .Values.secrets.create -}}{{ include "cs.name" . }}{{- else -}}{{ required "existingSecret is required" .Values.existingSecret }}{{- end -}}
{{- end -}}
{{- define "cs.env" -}}
- name: CLOUDSCOPE_DATABASE_URL
  valueFrom:
    secretKeyRef: {name: {{ include "cs.secret" . }}, key: DATABASE_URL}
- name: CLOUDSCOPE_SECRET_KEY
  valueFrom:
    secretKeyRef: {name: {{ include "cs.secret" . }}, key: SECRET_KEY}
- name: CLOUDSCOPE_ACCOUNTS_FILE
  value: /app/config/accounts.yaml
- name: CLOUDSCOPE_COOKIE_SECURE
  value: {{ .Values.api.cookieSecure | quote }}
- name: CLOUDSCOPE_COLLECT_CONCURRENCY
  value: {{ .Values.collector.concurrency | quote }}
- name: CLOUDSCOPE_NETWORK_ENABLED
  value: {{ .Values.collector.networkEnabled | default false | quote }}
- name: CLOUDSCOPE_LOAD_BALANCERS_ENABLED
  value: {{ .Values.collector.loadBalancersEnabled | default false | quote }}
- name: CLOUDSCOPE_DEDICATED_CREDENTIALS_ENABLED
  value: {{ .Values.accountCredentials.enabled | quote }}
- name: CLOUDSCOPE_CREDENTIALS_NAMESPACE
  value: {{ .Values.accountCredentials.namespace | quote }}
- name: CLOUDSCOPE_CREDENTIALS_OWNER
  value: {{ .Release.Name | quote }}
{{- range $key := list "AWS_ACCESS_KEY_ID" "AWS_SECRET_ACCESS_KEY" "AWS_SESSION_TOKEN" "ALIBABA_CLOUD_ACCESS_KEY_ID" "ALIBABA_CLOUD_ACCESS_KEY_SECRET" }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef: {name: {{ include "cs.secret" $ }}, key: {{ $key }}, optional: true}
{{- end }}
{{- end -}}
{{- define "cs.security" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities: {drop: [ALL]}
{{- end -}}
{{- define "cs.backendPod" -}}
# Service links would inject e.g. CLOUDSCOPE_API_PORT=tcp://... from the
# <release>-api Service, which collides with the app's CLOUDSCOPE_* settings.
enableServiceLinks: false
serviceAccountName: {{ if .Values.accountCredentials.enabled }}{{ include "cs.name" . }}-{{ .component }}-credentials{{ else }}{{ .Values.serviceAccount.name }}{{ end }}
automountServiceAccountToken: false
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  fsGroup: 10001
  seccompProfile: {type: RuntimeDefault}
imagePullSecrets: {{ .Values.imagePullSecrets | toJson }}
volumes:
  - name: accounts
    configMap: {name: {{ include "cs.name" . }}-accounts}
  - name: tmp
    emptyDir: {}
{{- if .Values.accountCredentials.enabled }}
  - name: credential-api-token
    projected:
      defaultMode: 0440
      sources:
        - serviceAccountToken: {path: token, expirationSeconds: 3600}
        - configMap:
            name: kube-root-ca.crt
            items: [{key: ca.crt, path: ca.crt}]
{{- end }}
{{- end -}}
{{- define "cs.mounts" -}}
- {name: accounts, mountPath: /app/config, readOnly: true}
- {name: tmp, mountPath: /tmp}
{{- if .Values.accountCredentials.enabled }}
- {name: credential-api-token, mountPath: /var/run/secrets/kubernetes.io/serviceaccount, readOnly: true}
{{- end }}
{{- end -}}
