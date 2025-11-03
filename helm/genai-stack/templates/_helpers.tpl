{{- define "genai-stack.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "genai-stack.fullname" -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "genai-stack.labels" -}}
app.kubernetes.io/name: {{ include "genai-stack.name" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "genai-stack.selectorLabels" -}}
app.kubernetes.io/name: {{ include "genai-stack.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "genai-stack.component.labels" -}}
{{ include "genai-stack.labels" . }}
app.kubernetes.io/component: {{ .componentName }}
{{- end -}}

{{- define "genai-stack.component.selectorLabels" -}}
{{ include "genai-stack.selectorLabels" . }}
app.kubernetes.io/component: {{ .componentName }}
{{- end -}}
