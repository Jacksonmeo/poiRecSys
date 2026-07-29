import { createApp } from "vue"
import ElementPlus from "element-plus"
import { createPinia } from "pinia"
import "element-plus/dist/index.css"
import App from "./App.vue"
import router from "./router"
import "./styles/main.css"

/**
 * 前端应用入口。
 * input: index.html 中的 #app DOM 容器。
 * output: 注册 Pinia、Router、Element Plus 后挂载 Vue 应用。
 * 插件注册集中在入口文件，业务页面不需要关心全局基础设施。
 */
createApp(App).use(createPinia()).use(router).use(ElementPlus).mount("#app")
