import { computed, onMounted, ref } from "vue"
import { fetchModelMetrics } from "@/api/metrics"
import { buildDashboardMetrics, resolveBestModel } from "@/utils/modelMetrics"
import type { ModelMetric } from "@/types/model"

/**
 * Dashboard 指标数据流封装。
 * input: 无，由组件挂载后主动请求后端模型指标接口。
 * output: loading、metrics、bestModel、metricCards，供页面组合组件使用。
 * 将请求与派生数据移出页面，避免 Dashboard.vue 堆积业务逻辑。
 */
export const useDashboardMetrics = () => {
  const metrics = ref<ModelMetric[]>([])
  const loading = ref(false)

  const bestModel = computed(() => resolveBestModel(metrics.value))
  const metricCards = computed(() => buildDashboardMetrics(bestModel.value))

  const loadMetrics = async () => {
    loading.value = true
    try {
      metrics.value = await fetchModelMetrics()
    } finally {
      loading.value = false
    }
  }

  onMounted(loadMetrics)

  return {
    bestModel,
    loading,
    metricCards,
    metrics,
    reload: loadMetrics,
  }
}
