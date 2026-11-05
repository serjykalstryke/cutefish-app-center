#define main cutefish_app_center_program_main
#include "../src/main.cpp"
#undef main
#include <cassert>
#include <ui/test_input.h>
#include <ui/keys.h>

template<class T> static T* findView(ui::View* root,std::function<bool(T*)> match) {
    if(auto* view=dynamic_cast<T*>(root);view && match(view))return view;
    for(auto& child:root->children())if(auto* view=findView<T>(child.get(),match))return view;
    return nullptr;
}
static ui::Label* findLabel(ui::View* root,const std::string& text) {
    return findView<ui::Label>(root,[&](auto* label){return label->text()==text;});
}
static void click(ui::Window& window,ui::View* view) {
    assert(view);
    for(auto* parent=view->parent();parent;parent=parent->parent())if(auto* scroll=dynamic_cast<ui::ScrollView*>(parent)){
        auto point=view->mapToWindow({0,0});auto origin=scroll->contentView()->mapToWindow({0,0});
        scroll->ensureVisible({point.x-origin.x,point.y-origin.y,view->geometry().width,view->geometry().height});
    }
    window.grab();auto point=view->mapToWindow({view->geometry().width/2,view->geometry().height/2});ui::TestInput::click(window,point);
}
int main(int argc,char** argv) {
    bool live=argc>1 && std::string(argv[1])=="--live";
    if(live)std::filesystem::create_directories("outputs");
    std::filesystem::create_directories("work/details-fixture");
    if(!live){
        std::string backend=(std::filesystem::path(__FILE__).parent_path()/"details_fixture.py").string();
        setenv("CUTEFISH_APP_CENTER_BACKEND",backend.c_str(),1);
        auto temp=std::filesystem::absolute("work/details-fixture").string();setenv("APP_CENTER_DETAILS_FIXTURE_DIR",temp.c_str(),1);
        std::filesystem::remove("work/details-fixture/launch.json");
    }
    ui::Application app(argc,argv,ui::Application::Platform::Headless);
    AppCenter store(app,false);store.show();auto& window=store.window();window.grab();
    assert(app.mainMenu());assert(app.mainMenu()->submenu(0)->role()==ui::MenuRole::Application);
    assert(app.mainMenu()->submenu(1));assert(app.mainMenu()->submenu(2));
    assert(!findLabel(window.contentView(),"Cutefish App Center"));
    auto* header=findView<ui::WindowHeader>(window.contentView(),[](auto*){return true;});
    assert(header);assert(header->mapToWindow({0,0}).y==0);assert(header->geometry().width==192);
    auto* search=findView<ui::SearchField>(window.contentView(),[](auto*){return true;});
    click(window,search);ui::TestInput::setKeyboardFocus(window,true);ui::TestInput::typeText(window,live?"firefox":"example");
    base::Timer poll(&app.loop());int stage=0,ticks=0;
    poll.onTimeout=[&]{
        if(++ticks>250){std::cerr<<"Timed out waiting for details stage "<<stage<<"\n";app.quit(1);return;}
        window.grab();auto* root=window.contentView();
        if(stage==0 && findLabel(root,live?"Mozilla":"Example Team") && findLabel(root,"Screenshots") && !findLabel(root,"Loading app details…")){
            auto* image=findView<ui::ImageView>(root,[](auto* view){return view->status()==ui::ImageView::Status::Ready;});
            if(!image)return;
            if(live){assert(window.grab().savePng("outputs/app-details.png"));std::cout<<"Live Firefox details, publisher, icon and screenshot rendered.\n";app.quit();return;}
            assert(findLabel(root,"Open"));assert(findLabel(root,"Remove"));assert(findLabel(root,"1 / 2"));
            click(window,findLabel(root,"Open"));stage=1;
        } else if(stage==1 && std::filesystem::exists("work/details-fixture/launch.json")){
            auto* combo=findView<ui::ComboBox>(root,[](auto* view){return view->items().size()==2 && view->items()[0].starts_with("Flatpak");});assert(combo);
            combo->setCurrentIndex(1);combo->onActivated(1);stage=2;
        } else if(stage==2 && findLabel(root,"Example Team") && findLabel(root,"Install") && !findLabel(root,"Loading app details…")){
            assert(!findLabel(root,"Open"));assert(findLabel(root,"Available"));assert(findLabel(root,"Second screenshot")==nullptr);
            auto* next=findView<ui::Button>(root,[](auto* button){return button->toolTip()=="Next screenshot";});
            click(window,next);assert(findLabel(root,"2 / 2"));assert(findLabel(root,"Second screenshot"));
            click(window,findLabel(root,"Enlarge…"));stage=3;
        } else if(stage==3 && app.windows().size()>1){
            bool found=false;for(auto* candidate:app.windows())if(candidate!=&window && findView<ui::ImageView>(candidate->contentView(),[](auto*){return true;}))found=true;
            assert(found);std::cout<<"Native details, source switching, Open dispatch, gallery, global menu and sidebar passed.\n";app.quit();
        }
    };
    poll.start(100ms);return app.run();
}
