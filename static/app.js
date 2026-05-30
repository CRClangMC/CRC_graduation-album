document.addEventListener('DOMContentLoaded', () => {
    const imagesPerPage = 20;
    const totalImages = 683;
    const totalPages = Math.ceil(totalImages / imagesPerPage);
    
    const imageContainer = document.getElementById('image-container');
    const loader = document.getElementById('loader');
    const currentPageSpan = document.getElementById('currentPage');
    const totalPageSpan = document.getElementById('totalPage');
    
    let currentPage = 1;
    let loading = false;

    // 初始化分页信息
    totalPageSpan.textContent = totalPages;
    
    // 格式化文件名为 fl (X).jpg
    function getFileName(index) {
        return `fl (${index}).jpg`;
    }

    // 创建图片元素的包装函数
    function createImageElement(fileName, index) {
        const imgWrapper = document.createElement('div');
        imgWrapper.className = 'image-item';
        
        const img = document.createElement('img');
        img.src = `/static/images/${fileName}`; // 修改路径为 /static/images/
        img.alt = `图片 ${index}`;
        img.loading = 'lazy';
        
        const downloadBtn = document.createElement('a');
        downloadBtn.href = img.src;
        downloadBtn.download = fileName;
        downloadBtn.className = 'download-btn';
        downloadBtn.textContent = '下载';
        
        imgWrapper.appendChild(img);
        imgWrapper.appendChild(downloadBtn);
        return imgWrapper;
    }

    // 加载指定页码的图片
    async function loadPage(pageNumber) {
        if (loading || pageNumber < 1 || pageNumber > totalPages) return;
        
        loading = true;
        loader.style.display = 'block';
        imageContainer.innerHTML = ''; // 清空现有内容
        
        const startIndex = (pageNumber - 1) * imagesPerPage + 1;
        const endIndex = Math.min(startIndex + imagesPerPage - 1, totalImages);
        
        // 创建图片元素
        const fragment = document.createDocumentFragment();
        for (let i = startIndex; i <= endIndex; i++) {
            const fileName = getFileName(i);
            const imgElement = createImageElement(fileName, i);
            fragment.appendChild(imgElement);
        }
        
        // 批量添加到DOM
        imageContainer.appendChild(fragment);
        currentPageSpan.textContent = pageNumber;
        loading = false;
        loader.style.display = 'none';
    }

    // 绑定按钮事件
    document.getElementById('prevBtn').addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            loadPage(currentPage);
        }
    });

    document.getElementById('nextBtn').addEventListener('click', () => {
        if (currentPage < totalPages) {
            currentPage++;
            loadPage(currentPage);
        }
    });

    // 初始化第一页
    loadPage(currentPage);
});