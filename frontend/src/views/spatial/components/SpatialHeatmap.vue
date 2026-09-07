<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue"
import MapContainer from "@/components/map/MapContainer.vue"
import type { DensityCell } from "@/types/spatial"

const props = defineProps<{ cells: DensityCell[] }>()

const mapRef = ref<InstanceType<typeof MapContainer>>()

/**
 * 空间热力图：把密度格网数据渲染到 Mapbox heatmap 图层。
 * 数据由父组件通过 props.cells 传入，变化时自动刷新图层。
 */
onMounted(() => mapRef.value?.setDensityLayer(props.cells))
watch(
  () => props.cells,
  (cells) => mapRef.value?.setDensityLayer(cells),
)
onBeforeUnmount(() => mapRef.value?.clearDensityLayer())
</script>

<template>
  <MapContainer ref="mapRef" />
</template>
